const fs = require('node:fs');
const ts = require(require('node:os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
const source = JSON.parse(fs.readFileSync(0, 'utf8')).source;
const file = ts.createSourceFile('candidate.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const printer = ts.createPrinter({removeComments: false});
const reactStates = new Set();
for (const node of file.statements) {
  if (ts.isImportDeclaration(node) && node.moduleSpecifier.text === 'react') {
    const bindings = node.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings)) {
      for (const item of bindings.elements) if ((item.propertyName || item.name).text === 'useState') reactStates.add(item.name.text);
    }
  }
}
function pure(node) {
  if (!node) return false;
  if (ts.isLiteralExpression(node) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind)) return true;
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return true;
  if (ts.isArrayLiteralExpression(node)) return node.elements.every(pure);
  if (ts.isObjectLiteralExpression(node)) return node.properties.every(p => ts.isPropertyAssignment(p) && !ts.isComputedPropertyName(p.name) && pure(p.initializer));
  if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node) || ts.isParenthesizedExpression(node)) return pure(node.expression);
  if (!ts.isCallExpression(node) || !ts.isIdentifier(node.expression) || !reactStates.has(node.expression.text) || node.arguments.length !== 1) return false;
  let initial = node.arguments[0];
  while (ts.isAsExpression(initial) || ts.isTypeAssertionExpression(initial) || ts.isParenthesizedExpression(initial)) initial = initial.expression;
  return !ts.isArrowFunction(initial) && !ts.isFunctionExpression(initial) && pure(initial);
}
const scopes = new Map(), duplicates = [];
function visit(node) {
  if (ts.isVariableStatement(node) && (node.declarationList.flags & (ts.NodeFlags.Const | ts.NodeFlags.Let)) && node.declarationList.declarations.every(d => pure(d.initializer))) {
    let seen = scopes.get(node.parent);
    if (!seen) scopes.set(node.parent, seen = new Set());
    const key = printer.printNode(ts.EmitHint.Unspecified, node, file);
    if (seen.has(key)) duplicates.push({start: Buffer.byteLength(source.slice(0, node.getStart(file))), end: Buffer.byteLength(source.slice(0, node.end)), declaration: key.slice(0, 160)});
    else seen.add(key);
  }
  ts.forEachChild(node, visit);
}
visit(file);
process.stdout.write(JSON.stringify({duplicates}));
