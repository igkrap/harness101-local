const ts = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');

function normalizeReturn(kind, code) {
  if (!['JsxElement','JsxFragment','JsxSelfClosingElement'].includes(kind)) return code;
  const sourceFile = ts.createSourceFile('temp.tsx', code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const diagnostics = sourceFile.parseDiagnostics;
  if (diagnostics.length > 0) return code;

  const statements = sourceFile.statements;
  if (statements.length !== 1 || statements[0].kind !== ts.SyntaxKind.ReturnStatement) {
    return code;
  }

  const returnStmt = statements[0];
  let expression = returnStmt.expression;
  if (!expression) return code;

  while (expression.kind === ts.SyntaxKind.ParenthesizedExpression) {
    expression = expression.expression;
  }

  const validKinds = [
    ts.SyntaxKind.JsxElement,
    ts.SyntaxKind.JsxFragment,
    ts.SyntaxKind.JsxSelfClosingElement
  ];

  if (!validKinds.includes(expression.kind)) {
    return code;
  }

  return code.slice(expression.getStart(sourceFile), expression.getEnd(sourceFile));
}

module.exports = { normalizeReturn };
