const { readdir, readFile } = require('node:fs/promises');
const { join } = require('node:path');

async function walk(dir, ctx) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const res = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules') await walk(res, ctx);
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      const content = await readFile(res, 'utf8');
      if (dir === join(ctx.root, 'frontend', 'src', 'screens') && res.endsWith('.tsx')) {
        const hasMeta = /export\s+const\s+meta\s*=/g.test(content);
        const hasDefault = /export\s+default\s+/g.test(content);
        if (!hasMeta || !hasDefault) {
          ctx.assert.fail(`${res}: add export const meta = { title: screen title } and a default component; a mere imported meta variable does not count`);
        }
        // A program (meta.code) must be findable: the sidebar search indexes meta.keywords (synonyms users type).
        const meta = content.match(/export\s+const\s+meta\s*=\s*\{([^{}]*(?:\[[^\]]*\][^{}]*)*)\}/);
        if (meta && /\bcode\s*:/.test(meta[1])) {
          const keywords = meta[1].match(/\bkeywords\s*:\s*\[([^\]]*)\]/);
          const count = keywords ? (keywords[1].match(/['"`][^'"`]+['"`]/g) || []).length : 0;
          if (count < 2) ctx.assert.fail(`${res}: add search keywords to meta, e.g. keywords: ['직원', '인사'] (at least 2 words users would type to find this screen; the sidebar search indexes them)`);
        }
      }
      const forbidden = [
        { reg: /@ts-ignore|@ts-nocheck|@ts-expect-error/g, msg: 'TS suppression directive' },
        { reg: /as\s+any/g, msg: 'as any cast' }
      ];
      for (const { reg, msg } of forbidden) {
        const matches = content.match(reg);
        if (matches) {
          ctx.assert.fail(`${res}: Found ${msg} (${matches[0]})`);
        }
      }
    }
  }
}

module.exports = async function check(ctx) {
  await walk(join(ctx.root, 'frontend', 'src'), ctx);
};
