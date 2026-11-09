// Trusted test infrastructure: supervise one isolated backend over a JSON-lines pipe.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

class ItemRuntime {
  constructor(output) {
    this.output = path.resolve(output);
    this.pending = new Map();
    this.sequence = 0;
    this.stderr = '';
    this.buffer = '';
    this.exit = null;
  }

  async start() {
    fs.mkdirSync(this.output, { recursive: true });
    this.child = spawn('python3', [path.resolve(__dirname, '../item_crud_runtime.py'), '--output', this.output], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.exited = new Promise(resolve => this.child.once('exit', (code, signal) => {
      this.exit = { code, signal };
      this.fail(new Error(`Isolated backend driver exited (${code ?? signal})`));
      resolve(this.exit);
    }));
    const ready = new Promise((resolve, reject) => {
      this.readyResolve = resolve;
      this.readyReject = reject;
    });
    this.child.on('error', error => this.fail(error));
    this.child.stdin.on('error', error => this.fail(error));
    this.child.stderr.on('data', data => { this.stderr = (this.stderr + data.toString()).slice(-200000); });
    this.child.stdout.on('data', data => {
      this.buffer += data.toString();
      if (this.buffer.length > 1000000) return this.fail(new Error('Isolated backend protocol response exceeded its limit'));
      let newline;
      while ((newline = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, newline);
        this.buffer = this.buffer.slice(newline + 1);
        if (!line.trim()) continue;
        let message;
        try { message = JSON.parse(line); }
        catch (_) { this.fail(new Error('Malformed isolated backend protocol response: ' + line.slice(0, 300))); continue; }
        if (message.event === 'ready') {
          this.info = message;
          this.readyResolve?.(message);
          this.readyResolve = this.readyReject = null;
        } else if (message.event === 'error') {
          this.fail(new Error(message.error || 'Isolated backend startup failed'));
        } else if (this.pending.has(message.id)) {
          const waiter = this.pending.get(message.id);
          this.pending.delete(message.id);
          clearTimeout(waiter.timer);
          if (message.ok) waiter.resolve(message);
          else waiter.reject(new Error(message.error || 'Isolated backend operation failed'));
        }
      }
    });
    const timer = setTimeout(() => this.fail(new Error('Isolated backend startup exceeded 110 seconds')), 110000);
    try {
      const info = await ready;
      const url = new URL(info.base_url);
      if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Backend must use a dedicated loopback URL');
      if (!info.db_name || !info.container_id) throw new Error('Backend ownership metadata is missing');
      return info;
    } finally { clearTimeout(timer); }
  }

  fail(error) {
    this.readyReject?.(error);
    this.readyResolve = this.readyReject = null;
    for (const waiter of this.pending.values()) { clearTimeout(waiter.timer); waiter.reject(error); }
    this.pending.clear();
  }

  request(op, fields = {}, timeout = 15000) {
    if (!this.child || this.exit || this.child.stdin.destroyed) return Promise.reject(new Error('Isolated backend driver is not available'));
    const id = 'oracle-' + (++this.sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('Isolated backend operation timed out: ' + op));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, op, ...fields }) + '\n');
    });
  }

  async rows(query) {
    const result = await this.request('sql', { query });
    if (!Array.isArray(result.rows)) throw new Error('SQL proof must return a row array');
    return result.rows;
  }

  async seedQueryFixture() {
    const result = await this.request('seed_query_fixture');
    if (result.fixture !== 'item-query-v1' || !Array.isArray(result.rows) || result.rows.length !== 2 ||
        result.rows.some(row => !row || !Number.isSafeInteger(row.id) || row.id <= 0) ||
        result.rows[0].id === result.rows[1].id) throw new Error('Query fixture proof is invalid');
    return result.rows;
  }

  async close() {
    if (!this.child) return { success: true, started: false };
    let response, error;
    try {
      if (!this.exit && this.info) response = await this.request('close', {}, 30000);
    } catch (failure) { error = failure; }
    this.child.stdin.end(); // EOF also requests cleanup if startup/operation failed.
    let timer;
    try {
      await Promise.race([this.exited, new Promise((_, reject) => {
        timer = setTimeout(() => { this.child.kill('SIGTERM'); reject(new Error('Backend cleanup did not exit within 35 seconds')); }, 35000);
      })]);
    } finally {
      clearTimeout(timer);
      fs.writeFileSync(path.join(this.output, 'driver-stderr.log'), this.stderr);
    }
    if (error) throw error;
    if (response) {
      if (this.exit?.code !== 0 || response.cleanup?.success !== true) throw new Error('Isolated backend cleanup was not verified: ' + JSON.stringify(response.cleanup));
      return response.cleanup;
    }
    // Startup failures return their own cleanup proof in the runtime evidence.
    const cleanupPath = path.join(this.output, 'cleanup.json');
    if (fs.existsSync(cleanupPath)) {
      const cleanup = JSON.parse(fs.readFileSync(cleanupPath, 'utf8'));
      if (cleanup.success === true) return cleanup;
    }
    throw new Error('Isolated backend exited without a verified cleanup result');
  }
}

module.exports = { ItemRuntime };
