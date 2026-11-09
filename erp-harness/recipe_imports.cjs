// Parse exact top-level source dependencies; comments and strings are not imports.
const fs = require('node:fs');
const ts = require(require('node:os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const sf = ts.createSourceFile(input.path, input.source, ts.ScriptTarget.Latest, true,
    /\.[jt]sx$/.test(input.path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  if (sf.parseDiagnostics.length) throw new Error('Recipe source has syntax errors');
  const dependencies = [...new Set(sf.statements.filter(node =>
    (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
  ).map(node => node.moduleSpecifier.text))];
  process.stdout.write(JSON.stringify({imports: dependencies.slice(0, 32), omitted: Math.max(0, dependencies.length - 32)}));
} catch (error) {
  process.stdout.write(JSON.stringify({error: error.message}));
  process.exitCode = 1;
}
