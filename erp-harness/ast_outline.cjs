const fs = require('fs');
const { compactSymbol } = require('./ast_compact_symbol.cjs');
const ts = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { path, source, symbol: targetSymbol } = input;
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : path.endsWith('.jsx') ? ts.ScriptKind.JSX : path.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS;
  const sf = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, kind);

  const imports = [];
  const tags = [];
  const symbols = [];
  const nodes = [];

  const getMeta = (n) => {
    const s = n.getStart(sf), e = n.getEnd();
    const sl = sf.getLineAndCharacterOfPosition(s), el = sf.getLineAndCharacterOfPosition(e);
    return { name: n.name ? n.name.getText(sf) : 'default', kind: ts.SyntaxKind[n.kind], start_line: sl.line + 1, start_column: sl.character + 1, end_line: el.line + 1, end_column: el.character + 1 };
  };

  function visit(n) {
    if (ts.isImportDeclaration(n)) imports.push(n.getText(sf).slice(0, 400));
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) tags.push(n.tagName.getText(sf));
    
    let isSym = false;
    if (ts.isFunctionDeclaration(n) || ts.isClassDeclaration(n) || ts.isMethodDeclaration(n) || ts.isInterfaceDeclaration(n) || ts.isTypeAliasDeclaration(n) || ts.isEnumDeclaration(n)) isSym = true;
    if (ts.isVariableDeclaration(n) && (n.initializer && (ts.isArrowFunction(n.initializer) || ts.isFunctionExpression(n.initializer)))) isSym = true;
    
    if (isSym) {
      symbols.push(getMeta(n));
      nodes.push(n);
    }
    ts.forEachChild(n, visit);
  }
  visit(sf);

  let result = {
    engine: 'typescript-ast',
    path,
    imports: imports.slice(0, 30),
    symbols: symbols.slice(0, 80),
    jsx_tags: [...new Set(tags)].sort().slice(0, 60),
    diagnostics: sf.parseDiagnostics.slice(0, 10).map(d => {
      const pos = sf.getLineAndCharacterOfPosition(d.start);
      return { message: ts.flattenDiagnosticMessageText(d.messageText, '\n'), line: pos.line + 1, column: pos.character + 1 };
    })
  };

  if (targetSymbol) {
    const matches = symbols.filter(s => s.name === targetSymbol);
    if (matches.length !== 1) throw new Error(`Symbol ${targetSymbol} must have exactly one match`);
    const idx = symbols.findIndex(s => s.name === targetSymbol);
    const node = nodes[idx];
    const fullText = input.compact ? compactSymbol(ts, sf, node) : node.getText(sf);
    const text = fullText.slice(0, 5000);
    result.symbol = { ...matches[0], source: text, truncated: fullText.length > 5000 };
  }

  console.log(JSON.stringify(result));
} catch (e) {
  console.log(JSON.stringify({ error: e.message }));
  process.exitCode = 1;
}
