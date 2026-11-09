// Bounded nested handler scopes; module/component functions stay outside this policy.
const ts = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
const MAX_HANDLER_CHARS = 3000;

function containsJsx(node) {
  let found = false;
  function walk(current) {
    if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current) || ts.isJsxFragment(current)) found = true;
    if (!found) ts.forEachChild(current, walk);
  }
  walk(node);
  return found;
}

function containsModuleSyntax(node) {
  let found = false;
  function walk(current) {
    if (ts.isImportDeclaration(current) || ts.isImportEqualsDeclaration(current) ||
        ts.isExportDeclaration(current) || ts.isExportAssignment(current) ||
        (current.modifiers || []).some(modifier => modifier.kind === ts.SyntaxKind.ExportKeyword ||
          modifier.kind === ts.SyntaxKind.DefaultKeyword)) found = true;
    if (!found) ts.forEachChild(current, walk);
  }
  walk(node);
  return found;
}

function handlerShape(node) {
  return ts.isFunctionDeclaration(node) && node.name && node.body && !node.asteriskToken &&
    !/^[A-Z]/.test(node.name.text) &&
    !(node.modifiers || []).some(modifier => modifier.kind !== ts.SyntaxKind.AsyncKeyword) &&
    !containsJsx(node) && !containsModuleSyntax(node);
}

function eligibleNestedHandler(node, sourceFile) {
  if (!handlerShape(node) || node.getText(sourceFile).length > MAX_HANDLER_CHARS) return false;
  for (let parent = node.parent; parent && !ts.isSourceFile(parent); parent = parent.parent)
    if (ts.isFunctionLike(parent)) return true;
  return false;
}

function eligibleHandlerStatement(node) {
  if (!ts.isStatement(node) || ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) return false;
  const block = node.parent, handler = block && block.parent;
  if (!block || !ts.isBlock(block) || !handlerShape(handler) || handler.body !== block) return false;
  for (let parent = handler.parent; parent && !ts.isSourceFile(parent); parent = parent.parent)
    if (ts.isFunctionLike(parent)) return true;
  return false;
}

function validateHandlerStatements(code) {
  if (typeof code !== 'string' || !code.trim() || code.length > MAX_HANDLER_CHARS)
    throw new Error('Local handler statements require complete code within the 3000-character bound');
  const sf = ts.createSourceFile('statements.tsx', code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (sf.parseDiagnostics.length || !sf.statements.length ||
      !sf.statements.every(statement => ts.isStatement(statement)) || containsJsx(sf) || containsModuleSyntax(sf))
    throw new Error('Local handler statement scope accepts complete local statements, without JSX or module syntax');
}

function tokenIdentity(node, sourceFile) {
  if (!node) return null;
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.Standard, node.getText(sourceFile));
  const tokens = [];
  for (let kind = scanner.scan(); kind !== ts.SyntaxKind.EndOfFileToken; kind = scanner.scan())
    tokens.push([kind, scanner.getTokenText()]);
  return JSON.stringify(tokens);
}

function parseHandler(source) {
  const sf = ts.createSourceFile('handler.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (sf.parseDiagnostics.length || sf.statements.length !== 1 || !handlerShape(sf.statements[0]))
    throw new Error('Nested handler scope requires one named non-component function; no exports/defaults, generators, or JSX');
  return [sf.statements[0], sf];
}

function validateHandler(original, replacement) {
  if (typeof original !== 'string' || typeof replacement !== 'string' ||
      !replacement.trim() || original.length > MAX_HANDLER_CHARS || replacement.length > MAX_HANDLER_CHARS)
    throw new Error('Nested handler scope requires a complete function within the 3000-character bound');
  const [before, oldFile] = parseHandler(original), [after, newFile] = parseHandler(replacement);
  const identity = (node, sf) => ({ name: node.name.text,
    parameters: node.parameters.map(parameter => tokenIdentity(parameter, sf)),
    typeParameters: (node.typeParameters || []).map(parameter => tokenIdentity(parameter, sf)),
    returnType: tokenIdentity(node.type, sf) });
  if (JSON.stringify(identity(before, oldFile)) !== JSON.stringify(identity(after, newFile)))
    throw new Error('Nested handler identity and parameters/type signature must stay unchanged; only async modifier and body may change');
}

module.exports = { eligibleNestedHandler, validateHandler, eligibleHandlerStatement, validateHandlerStatements, MAX_HANDLER_CHARS };
