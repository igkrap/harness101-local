const ts = require(require('node:os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');

// Expand only mechanical operations selected by the model. Children and peer
// imports come from the current AST, never from generated application code.
function normalize(input) {
  const parse = text => ts.createSourceFile('candidate.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const file = parse(input.source);
  if (file.parseDiagnostics.length) throw new Error('Candidate must parse');
  const printer = ts.createPrinter();
  const canonical = (n, f) => printer.printNode(ts.EmitHint.Unspecified, n, f);
  const pos = n => [Buffer.byteLength(input.source.slice(0, n.getStart(file))), Buffer.byteLength(input.source.slice(0, n.end))].join(':');
  const actual = new Map(), catalog = new Map(input.nodes.map(n => [n.id, n]));
  const byRange = new Map(input.nodes.map(n => [n.kind + ':' + n.range.join(':'), n.id]));
  function visit(n) {
    if (ts.isJsxOpeningElement(n) || ts.isImportDeclaration(n)) actual.set(ts.SyntaxKind[n.kind] + ':' + pos(n), n);
    ts.forEachChild(n, visit);
  }
  visit(file);
  const output = new Map();
  function put(id, code) {
    if (output.has(id) && output.get(id) !== code) throw new Error('Conflicting structural edits for ' + id);
    output.set(id, code);
  }
  for (const edit of input.edits) {
    const info = catalog.get(edit.node_id);
    if (!info) throw new Error('Unknown AST target ' + edit.node_id);
    const anchor = actual.get(info.kind + ':' + info.range.join(':'));
    if (info.kind === 'ImportDeclaration' && edit.code.trim()) {
      const fragment = parse(edit.code);
      if (fragment.parseDiagnostics.length || !fragment.statements.length || fragment.statements.length > 16 || !fragment.statements.every(ts.isImportDeclaration))
        throw new Error('Import target accepts only import declarations, at most 16');
      if (!anchor) throw new Error('Import target is not indexed');
      const retained = [];
      const seen = new Set();
      for (const stmt of fragment.statements) {
        const key = canonical(stmt, fragment);
        if (seen.has(key)) continue;
        seen.add(key);
        const peer = file.statements.find(n => n !== anchor && ts.isImportDeclaration(n) && canonical(n, file) === key);
        if (!peer) retained.push(key === canonical(anchor, file) ? info.source : stmt.getFullText(fragment).trim());
      }
      const code = retained.join('\n');
      if (code.trim() !== info.source.trim()) put(edit.node_id, code);
      continue;
    }
    if (info.kind === 'JsxOpeningElement' && edit.code.trim()) {
      if (!anchor || !ts.isJsxElement(anchor.parent)) throw new Error('Opening tag has no matching full element');
      const match = edit.code.match(/^\s*<([A-Za-z_$][\w.$:-]*)\b/);
      if (!match) throw new Error('Expected a JSX opening tag');
      const fragment = parse('const element=(' + edit.code + '</' + match[1] + '>);');
      const expr = fragment.statements[0]?.declarationList?.declarations[0]?.initializer?.expression;
      if (fragment.parseDiagnostics.length || !expr || !ts.isJsxElement(expr) || expr.children.length)
        throw new Error('Opening tag edit must contain only one opening tag; children are preserved');
      const tag = expr.openingElement.tagName.getText(fragment);
      if (tag !== anchor.tagName.getText(file)) {
        const parent = anchor.parent;
        const id = byRange.get('JsxElement:' + pos(parent));
        if (!id) throw new Error('Matching full JSX element is not indexed');
        const children = input.source.slice(anchor.end, parent.closingElement.getStart(file));
        put(id, edit.code.trim() + children + '</' + tag + '>');
        continue;
      }
    }
    put(edit.node_id, edit.code);
  }
  return {...input, edits: [...output].map(([node_id, code]) => ({node_id, code}))};
}
module.exports = {normalize};
