// Read-only, bounded extraction of declarations and their exact local type dependencies.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const ts = require(path.join(os.homedir(), '.local/share/mlx-server/code-intelligence/node_modules/typescript'));

function resolve(input) {
  const root = path.resolve(input.root), sourceRoot = path.join(root, 'frontend/src');
  const source = input.source ? path.resolve(root, input.source) : null;
  if (input.source_text !== undefined && (typeof input.source_text !== 'string' || !source || input.source_text.length > 200000)) throw new Error('Invalid virtual source');
  const maxDepth = Math.min(3, Math.max(0, input.max_depth ?? 3));
  const maxDeclarations = Math.min(12, Math.max(1, input.max_declarations ?? 12));
  const maxChars = Math.min(4000, Math.max(128, input.max_chars ?? 4000));
  const modules = new Map(), omitted = [], declarations = [], resolved = [], ambiguous = [];
  const printer = ts.createPrinter({ removeComments: true });
  const exported = node => !!node.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword);
  const id = declaration => declaration.file + ':' + declaration.node.name.text;
  function omit(name, reason) {
    if (omitted.length < 24 && !omitted.some(item => item.name === name && item.reason === reason)) omitted.push({ name, reason });
  }
  function safe(file) {
    file = path.resolve(file);
    if (file === sourceRoot || !file.startsWith(sourceRoot + path.sep)) return false;
    let current = file;
    while (current !== root) {
      if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) return false;
      const parent = path.dirname(current);
      if (parent === current) return false;
      current = parent;
    }
    if (!/\.(?:ts|tsx)$/.test(file)) return false;
    if (file === source && typeof input.source_text === 'string') return true;
    return fs.existsSync(file) && fs.statSync(file).isFile() && fs.statSync(file).size <= 200000;
  }
  function moduleAt(file) {
    file = path.resolve(file);
    if (modules.has(file)) return modules.get(file);
    if (!safe(file)) return null;
    if (modules.size >= 250) throw new Error('Local type file limit reached; use a source-scoped lookup');
    const text = file === source && typeof input.source_text === 'string' ? input.source_text : fs.readFileSync(file, 'utf8');
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    if (sf.parseDiagnostics.length) return null;
    const data = { file, sf, declarations: new Map(), imports: new Map(), exports: new Map(), stars: [] };
    modules.set(file, data);
    for (const node of sf.statements) {
      if (ts.isTypeAliasDeclaration(node) || ts.isInterfaceDeclaration(node) || ts.isEnumDeclaration(node)) data.declarations.set(node.name.text, { file, node, sf });
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
        const from = node.moduleSpecifier.text, bindings = node.importClause?.namedBindings;
        if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements) data.imports.set(item.name.text, { from, name: item.propertyName?.text || item.name.text });
        if (bindings && ts.isNamespaceImport(bindings)) data.imports.set(bindings.name.text, { from, name: '*' });
      }
      if (ts.isExportDeclaration(node)) {
        const from = node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier) ? node.moduleSpecifier.text : null;
        if (node.exportClause && ts.isNamedExports(node.exportClause)) for (const item of node.exportClause.elements) data.exports.set(item.name.text, { from, name: item.propertyName?.text || item.name.text });
        else if (from && !node.exportClause) data.stars.push(from);
      }
    }
    return data;
  }
  function relativeModule(file, specifier) {
    if (!specifier?.startsWith('.')) return null;
    const target = path.resolve(path.dirname(file), specifier);
    const bases = /\.jsx?$/.test(target) ? [target.replace(/\.jsx?$/, '')] : [target];
    for (const base of bases) for (const candidate of [base, base + '.ts', base + '.tsx', base + '.d.ts', path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) if (safe(candidate)) return candidate;
    return null;
  }
  function unique(items) { return [...new Map(items.map(item => [id(item), item])).values()]; }
  function lookup(file, name, exportsOnly = false, seen = new Set()) {
    const key = file + ':' + name + ':' + exportsOnly;
    if (seen.has(key) || seen.size >= 32) return [];
    seen = new Set([...seen, key]);
    const data = moduleAt(file);
    if (!data) return [];
    const local = data.declarations.get(name);
    if (local && (!exportsOnly || exported(local.node))) return [local];
    const binding = exportsOnly ? data.exports.get(name) : data.imports.get(name) || data.exports.get(name);
    if (binding) {
      if (!binding.from) return lookup(file, binding.name, false, seen);
      const target = relativeModule(file, binding.from);
      return target ? lookup(target, binding.name, true, seen) : [];
    }
    if (!exportsOnly && name.includes('.')) {
      const [namespace, member, ...rest] = name.split('.'), imported = data.imports.get(namespace);
      const target = imported?.name === '*' && !rest.length && relativeModule(file, imported.from);
      return target ? lookup(target, member, true, seen) : [];
    }
    return unique(data.stars.flatMap(from => {
      const target = relativeModule(file, from);
      return target ? lookup(target, name, true, seen) : [];
    }));
  }
  function allFiles(directory, files = []) {
    if (!fs.existsSync(directory) || fs.lstatSync(directory).isSymbolicLink()) return files;
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) allFiles(file, files);
      else if (safe(file)) files.push(file);
      if (files.length > 250) throw new Error('Local type file limit reached; use a source-scoped lookup');
    }
    return files;
  }
  function importedContracts(file, name) {
    let frontier = [file];
    const seen = new Set([file]);
    for (let depth = 0; depth < 3 && frontier.length; depth++) {
      const next = [];
      for (const owner of frontier) {
        const data = moduleAt(owner);
        if (!data) continue;
        const froms = [...data.imports.values(), ...data.exports.values()].map(item => item.from).concat(data.stars);
        for (const from of new Set(froms)) {
          const target = relativeModule(owner, from);
          if (target && !seen.has(target)) {
            if (seen.size >= 64) { omit(name, 'import graph limit'); return []; }
            seen.add(target); next.push(target);
          }
        }
      }
      const matches = unique(next.flatMap(target => lookup(target, name, true)));
      if (matches.length) return matches;
      frontier = next;
    }
    return [];
  }
  if (source && !safe(source)) throw new Error('Local type source is outside frontend/src, missing, or unsafe');
  const files = source ? [] : allFiles(sourceRoot);
  const queue = [];
  for (const name of [...new Set(input.names)].slice(0, 12)) {
    let matches = unique(source ? lookup(source, name) : files.flatMap(file => lookup(file, name, true)));
    if (source && !matches.length) {
      // Compiler errors may name a nested contract of an imported component.
      matches = importedContracts(source, name);
    }
    if (matches.length === 1) queue.push({ declaration: matches[0], depth: 0, name, requested: name });
    else if (matches.length > 1) { ambiguous.push(name); omit(name, 'ambiguous local declaration'); }
  }
  const visited = new Set();
  let chars = 0;
  while (queue.length) {
    const item = queue.shift(), declaration = item.declaration;
    if (visited.has(id(declaration))) {
      if (item.requested && !resolved.includes(item.requested)) resolved.push(item.requested);
      continue;
    }
    if (item.depth > maxDepth) { omit(item.name, 'depth limit'); continue; }
    if (declarations.length >= maxDeclarations) { omit(item.name, 'declaration limit'); continue; }
    const text = printer.printNode(ts.EmitHint.Unspecified, declaration.node, declaration.sf).trim();
    const rel = path.relative(root, declaration.file).split(path.sep).join('/');
    const line = declaration.sf.getLineAndCharacterOfPosition(declaration.node.getStart(declaration.sf)).line + 1;
    const alias = item.name !== declaration.node.name.text ? ` (referenced as ${item.name})` : '';
    const record = `Project declaration ${rel}:${line}${alias}\n${text}`;
    if (chars + record.length + 1 > maxChars - Math.min(240, Math.floor(maxChars / 4))) { omit(item.name, 'character limit'); continue; }
    chars += record.length + 1;
    visited.add(id(declaration));
    declarations.push({ name: declaration.node.name.text, path: rel, line, source: text, record, depth: item.depth });
    if (item.requested) resolved.push(item.requested);
    const references = new Set(), parameters = new Set();
    function visit(node) {
      if (ts.isTypeParameterDeclaration(node)) parameters.add(node.name.text);
      if (ts.isTypeReferenceNode(node)) references.add(node.typeName.getText(declaration.sf));
      if (ts.isExpressionWithTypeArguments(node)) references.add(node.expression.getText(declaration.sf));
      ts.forEachChild(node, visit);
    }
    visit(declaration.node);
    for (const reference of references) {
      if (parameters.has(reference)) continue;
      const matches = unique(lookup(declaration.file, reference));
      if (matches.length === 1) queue.push({ declaration: matches[0], depth: item.depth + 1, name: reference });
      else if (matches.length > 1) omit(reference, 'ambiguous local declaration');
    }
  }
  return { declarations, omitted, resolved, ambiguous, total_chars: chars, max_chars: maxChars };
}

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!Array.isArray(input.names) || input.names.some(name => typeof name !== 'string' || !/^[\w$.]+$/.test(name))) throw new Error('Invalid type names');
  console.log(JSON.stringify(resolve(input)));
} catch (error) {
  console.log(JSON.stringify({ declarations: [], omitted: [], resolved: [], ambiguous: [], error: error.message }));
  process.exitCode = 1;
}
