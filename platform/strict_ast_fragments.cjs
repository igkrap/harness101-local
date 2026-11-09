const fs = require('node:fs');
const ts = require(require('node:os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const structural = Array.isArray(input) ? null : require('./normalize_structural_edits.cjs').normalize(input);
  const normalized = structural ? require('./normalize_declaration_edits.cjs').normalize(structural) : null;
  const groups = new Set(normalized?.groups || []);
  const fragments = normalized ? normalized.edits.map(edit => {
    const node = input.nodes.find(n => n.id === edit.node_id);
    return {...edit, kind: node.kind, original: node.source, handler_statement_scope: node.handler_statement_scope === true};
  }) : input;
  for (const [index, edit] of fragments.entries()) {
    if (!edit.code.trim()) continue;
    if (edit.handler_statement_scope === true) {
      require('../local-only/harness/ast_handler_scopes.cjs').validateHandlerStatements(edit.code);
      continue;
    }
    if (edit.kind === 'VariableStatement') {
      const file = ts.createSourceFile('fragment.tsx', edit.code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const original = ts.createSourceFile('original.tsx', edit.original, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const names = original.statements[0]?.declarationList?.declarations.map(d => d.name.getText(original)).join(', ');
      if (groups.has(edit.node_id)) {
        if (file.parseDiagnostics.length || !file.statements.every(ts.isVariableStatement))
          throw new Error('Normalized declaration group must contain only variables');
        continue;
      }
      if (file.statements.length !== 1 || !ts.isVariableStatement(file.statements[0]))
        throw new Error(`Fragment ${index + 1}, existing binding [${names}]: expected ONE VariableStatement, received ${file.statements.length} statements. Return only this binding's complete declaration. Use the other existing node IDs for other declarations; new declarations belong in insertion slots.`);
      if (file.statements[0].declarationList.declarations.length > original.statements[0].declarationList.declarations.length)
        throw new Error(`Fragment ${index + 1}, existing binding [${names}]: do not add unrelated declarations inside this variable node; use an insertion slot.`);
    }
    if (['JsxSelfClosingElement', 'JsxElement', 'JsxFragment'].includes(edit.kind)) {
      const file = ts.createSourceFile('fragment.tsx', `const x=(${edit.code});`, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const expr = file.statements[0]?.declarationList?.declarations[0]?.initializer?.expression;
      if (!file.parseDiagnostics.length && (!expr || expr.kind !== ts.SyntaxKind[edit.kind]))
        throw new Error(`Expected exactly ${edit.kind}; use the matching JSX node for the proposed fragment. A panel and a self-closing control are different edit targets.`);
    }
  }
  process.stdout.write(JSON.stringify({ok: true, edits: normalized?.edits}));
} catch (error) {
  process.stdout.write(JSON.stringify({ok: false, error: error.message}));
  process.exitCode = 1;
}
