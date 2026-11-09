const {validateInsert,validateOpening} = require('./ast_scope_rules.cjs');
const {normalizeReturn} = require('./ast_fragment_shape.cjs');
const {validateHandler,validateHandlerStatements} = require('./ast_handler_scopes.cjs');
const fs = require('fs');
const ts = require(require('os').homedir()+'/.local/share/mlx-server/code-intelligence/node_modules/typescript');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));

function validate() {
  for (const edit of input.edits) {
    edit.code = normalizeReturn(edit.kind, edit.code);
    const { kind, label, code } = edit;
    if (kind === 'FunctionDeclaration') {
      if (edit.nested_handler_scope !== true) throw new Error('Whole function replacement is not enabled for this scope');
      validateHandler(edit.original_code, code);
    }
    if (!code || code.trim() === '') continue;
    if (edit.handler_statement_scope === true) { validateHandlerStatements(code); continue; }
    if (kind === 'JsxOpeningElement') { validateOpening(code); continue; }
    if (kind === 'insert') { validateInsert(code, label); }

    let text = code;
    let scriptKind = ts.ScriptKind.TSX;

    if (kind === 'insert' && label.includes('JSX')) {
      text = `const __AST_EDIT__=(<>${code}</>);`;
    } else if (kind.startsWith('Jsx')) {
      text = `const __AST_EDIT__=(${code});`;
    }

    const sourceFile = ts.createSourceFile('fragment.tsx', text, ts.ScriptTarget.Latest, true, scriptKind);
    const diagnostics = sourceFile.parseDiagnostics;
    if (diagnostics.length > 0) {
      throw diagnosticError(diagnostics, code, text);
    }

    const statements = sourceFile.statements;
    if (kind === 'insert' && label.includes('JSX')) {
      if (statements.length !== 1 || !ts.isVariableStatement(statements[0])) throw new Error('Must be 1 VariableStatement');
      const decl = statements[0].declarationList.declarations;
      if (decl.length !== 1) throw new Error('Must have 1 declaration');
      const init = decl[0].initializer;
      if (!ts.isParenthesizedExpression(init) || !ts.isJsxFragment(init.expression)) throw new Error('Must be JSX fragment');
    } else if (kind.startsWith('Jsx')) {
      if (statements.length !== 1 || !ts.isVariableStatement(statements[0])) throw new Error('Must be 1 VariableStatement');
      const decl = statements[0].declarationList.declarations;
      if (decl.length !== 1) throw new Error('Must have 1 declaration');
      const init = decl[0].initializer;
      const expr = init.expression;
      if (!ts.isJsxElement(expr) && !ts.isJsxFragment(expr) && !ts.isJsxSelfClosingElement(expr)) throw new Error('Must be JSX element/fragment');
    } else if (kind !== 'insert') {
      const expectedKind = ts.SyntaxKind[kind];
      if (statements.length === 0 || !statements.every(s => s.kind === expectedKind)) {
        const actualKinds = [...new Set(statements.map(s => ts.SyntaxKind[s.kind]))].join(', ');
        throw new Error(`Expected kind ${kind}, got ${actualKinds || 'none'}`);
      }
    }
  }
  console.log(JSON.stringify({ ok: true, edits: input.edits }));
}

try {
  validate();
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: e.message, diagnostics: e.diagnostics || [] }));
  process.exitCode = 1;
}

function diagnosticError(diagnostics, code, text) {
  const error = new Error(ts.flattenDiagnosticMessageText(diagnostics[0].messageText, '\n'));
  const prefix = text.indexOf(code);
  error.diagnostics = diagnostics.map(d => {
    const offset = Math.max(0, Math.min(code.length, (d.start || 0) - prefix));
    const lines = code.slice(0, offset).split('\n');
    return {
      message: ts.flattenDiagnosticMessageText(d.messageText, '\n'),
      line: lines.length,
      column: lines[lines.length - 1].length + 1
    };
  });
  return error;
}
