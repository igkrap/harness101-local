const ts = require(require('node:os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
function normalize(input) {
  const file = ts.createSourceFile('candidate.tsx', input.source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (file.parseDiagnostics.length) throw new Error('Candidate must parse');
  const printer = ts.createPrinter({ removeComments: true });
  const canonical = (node, sf) => printer.printNode(ts.EmitHint.Unspecified, node, sf);
  const names = node => ts.isIdentifier(node) ? [node.text] :
    (ts.isArrayBindingPattern(node) || ts.isObjectBindingPattern(node)) ?
      node.elements.flatMap(e => ts.isBindingElement(e) ? names(e.name) : []) : [];
  const bindings = stmt => ts.isVariableStatement(stmt) ? stmt.declarationList.declarations.flatMap(d => names(d.name)) : [];
  const key = stmt => JSON.stringify(bindings(stmt).sort());
  const pos = n => [Buffer.byteLength(input.source.slice(0, n.getStart(file))), Buffer.byteLength(input.source.slice(0, n.end))].join(':');
  const actual = new Map();
  function visit(n) { if (ts.isVariableStatement(n)) actual.set(pos(n), n); ts.forEachChild(n, visit); }
  visit(file);
  const catalog = new Map(input.nodes.map(n => [n.id, n]));
  const byRange = new Map(input.nodes.filter(n => n.kind === 'VariableStatement').map(n => [n.range.join(':'), n.id]));
  const output = new Map(), groups = new Set(), introduced = new Set();
  function put(id, code) {
    if (!catalog.has(id)) throw new Error('Unknown AST target ' + id);
    if (code.trim() === catalog.get(id).source.trim()) return;
    if (output.has(id) && output.get(id) !== code) throw new Error('Conflicting edits for ' + id);
    output.set(id, code);
  }
  for (const edit of input.edits) {
    const info = catalog.get(edit.node_id);
    if (!info) throw new Error('Unknown AST target ' + edit.node_id);
    if (info.kind !== 'VariableStatement' || !edit.code.trim()) { put(edit.node_id, edit.code); continue; }
    const fragment = ts.createSourceFile('fragment.tsx', edit.code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    if (fragment.parseDiagnostics.length) throw new Error('Declaration group must parse');
    if (fragment.statements.length <= 1) { put(edit.node_id, edit.code); continue; }
    if (fragment.statements.length > 16) throw new Error('Declaration group exceeds 16 statements');
    const anchor = actual.get(info.range.join(':'));
    if (!anchor || !ts.isVariableStatement(anchor) || !ts.isBlock(anchor.parent))
      throw new Error('Declaration groups require a local block variable target');
    const scope = anchor.parent.statements;
    const existing = new Map(scope.filter(ts.isVariableStatement).map(s => [key(s), s]));
    const occupied = new Set(scope.flatMap(s => ts.isVariableStatement(s) ? bindings(s) : s.name && ts.isIdentifier(s.name) ? [s.name.text] : []));
    for (const p of anchor.parent.parent.parameters || []) for (const name of names(p.name)) occupied.add(name);
    const proposedVariables = [...fragment.statements].filter(ts.isVariableStatement);
    const peers = proposedVariables.map(stmt => existing.get(key(stmt))).filter(Boolean);
    const peerPositions = peers.map(stmt => scope.indexOf(stmt));
    const reordered = peerPositions.some((position, index) => index > 0 && position < peerPositions[index - 1]);
    if (reordered) {
      const first = Math.min(...peerPositions), last = Math.max(...peerPositions);
      const targetStatements = [...scope].slice(first, last + 1);
      const uniqueNames = proposedVariables.flatMap(bindings);
      if (proposedVariables.length !== fragment.statements.length
          || !peers.includes(anchor) || new Set(peers).size !== peers.length
          || new Set(uniqueNames).size !== uniqueNames.length || targetStatements.length !== peers.length
          || targetStatements.some(stmt => !ts.isVariableStatement(stmt) || !peers.includes(stmt))
          || proposedVariables.some(stmt => stmt.modifiers?.length || !(stmt.declarationList.flags & (ts.NodeFlags.Const | ts.NodeFlags.Let))))
        throw new Error('Declaration reorder must cover exactly one contiguous group of existing local const/let declarations; do not cross omitted statements');
      const chunks = [];
      let chunk = [];
      for (const stmt of proposedVariables) {
        const prior = existing.get(key(stmt));
        if (!prior) {
          const ids = bindings(stmt);
          if (!ids.length || ids.some(name => occupied.has(name) || introduced.has(name)))
            throw new Error('New declaration conflicts with an existing binding');
          ids.forEach(name => introduced.add(name));
        }
        chunk.push(stmt.getFullText(fragment).trim());
        if (prior) { chunks.push(chunk); chunk = []; }
      }
      if (chunk.length) chunks[chunks.length - 1].push(...chunk);
      targetStatements.forEach((stmt, index) => {
        const id = byRange.get(pos(stmt));
        if (!id) throw new Error('Reordered declaration has no indexed target');
        put(id, chunks[index].join('\n'));
        if (chunks[index].length > 1) groups.add(id);
      });
      continue;
    }
    const group = [], seen = new Set();
    let anchorCount = 0;
    for (const stmt of fragment.statements) {
      if (!ts.isVariableStatement(stmt)) {
        if (scope.some(s => canonical(s, file) === canonical(stmt, fragment))) continue;
        throw new Error('New non-declaration statements require their own insertion target');
      }
      if (stmt.modifiers?.length || !(stmt.declarationList.flags & (ts.NodeFlags.Const | ts.NodeFlags.Let)))
        throw new Error('Declaration groups allow local const/let only');
      const ids = bindings(stmt), k = key(stmt);
      if (!ids.length || ids.some(n => seen.has(n))) throw new Error('Repeated binding in declaration group');
      ids.forEach(n => seen.add(n));
      const code = stmt.getFullText(fragment).trim();
      const prior = existing.get(k);
      if (prior === anchor) { anchorCount++; group.push(code); continue; }
      if (prior) {
        if (canonical(prior, file) !== canonical(stmt, fragment)) {
          const id = byRange.get(pos(prior));
          if (!id) throw new Error('Related binding has no indexed target');
          put(id, code);
        }
        continue;
      }
      if (ids.some(n => occupied.has(n) || introduced.has(n))) throw new Error('New declaration conflicts with an existing binding');
      ids.forEach(n => introduced.add(n));
      group.push(code);
    }
    if (anchorCount !== 1) throw new Error('Declaration group must preserve the target binding exactly once');
    put(edit.node_id, group.join('\n'));
    if (group.length > 1) groups.add(edit.node_id);
  }
  return { edits: [...output].map(([node_id, code]) => ({node_id, code})), groups: [...groups] };
}
module.exports = { normalize };
