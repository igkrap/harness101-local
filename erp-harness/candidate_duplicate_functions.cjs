function deduplicate(ts_api, operations, name) {
  const matches = [];
  const printer = ts_api.createPrinter({ removeComments: true });

  for (const op of operations) {
    const sf = ts_api.createSourceFile('tmp.tsx', op.code, ts_api.ScriptTarget.Latest, true, ts_api.ScriptKind.TSX);
    if (sf.parseDiagnostics.length > 0) return [];

    for (const stmt of sf.statements) {
      if (stmt.kind !== ts_api.SyntaxKind.VariableStatement) continue;
      const decls = stmt.declarationList.declarations;
      if (decls.length !== 1) continue;
      const decl = decls[0];
      if (decl.name.kind !== ts_api.SyntaxKind.Identifier || decl.name.text !== name) continue;
      const init = decl.initializer;
      if (!init || (init.kind !== ts_api.SyntaxKind.ArrowFunction && init.kind !== ts_api.SyntaxKind.FunctionExpression)) continue;

      const canonical = printer.printNode(ts_api.EmitHint.Unspecified, stmt, sf);
      matches.push({
        op,
        canonical,
        start: stmt.getStart(sf),
        end: stmt.getEnd(sf)
      });
    }
  }

  if (matches.length !== 2) return [];
  const [m1, m2] = matches;
  if (m1.op.node_id === m2.op.node_id || m1.canonical !== m2.canonical) return [];

  const isIns1 = m1.op.is_insert === true;
  const isIns2 = m2.op.is_insert === true;
  const isRem1 = m1.op.is_insert === false;
  const isRem2 = m2.op.is_insert === false;

  if (!((isIns1 && isRem2) || (isIns2 && isRem1))) return [];

  const ins = isIns1 ? m1 : m2;
  const code = ins.op.code;
  const newCode = code.substring(0, ins.start) + code.substring(ins.end);

  if (newCode.trim() === '') return [];

  return [{ node_id: ins.op.node_id, code: newCode }];
}

module.exports = { deduplicate };
