// Built screens served the way an operating copy serves them, /api passed to the development server: what Lighthouse measures.
// node lighthouse_serve.mjs <built folder> <port> <api port>   (run from outside the project folder, so the platform never takes it for a preview)
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import zlib from 'node:zlib';
const [root, port, api] = [process.argv[2], Number(process.argv[3]), Number(process.argv[4])];
const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json' };
http.createServer((req, res) => {
  if (req.url.startsWith('/api')) {
    const up = http.request({ host: '127.0.0.1', port: api, path: req.url, method: req.method, headers: req.headers }, answer => { res.writeHead(answer.statusCode, answer.headers); answer.pipe(res); });
    req.pipe(up); up.on('error', () => { res.writeHead(502); res.end(); }); return;
  }
  let file = path.join(root, decodeURIComponent(req.url.split('?')[0]));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html');
  const ext = path.extname(file);
  const packed = /gzip/.test(req.headers['accept-encoding'] || '') && /\.(js|css|html|svg|json)$/.test(file);      // as the operating server does (server.compression)
  res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream', ...(packed ? { 'Content-Encoding': 'gzip', Vary: 'Accept-Encoding' } : {}),
    ...(file.includes('/assets/') ? { 'Cache-Control': 'public, max-age=31536000, immutable' } : {}) });
  const stream = fs.createReadStream(file);
  (packed ? stream.pipe(zlib.createGzip()) : stream).pipe(res);
}).listen(port, '127.0.0.1', () => console.log('ready'));
