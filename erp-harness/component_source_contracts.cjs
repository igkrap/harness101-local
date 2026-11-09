// Read-only component bindings from real JSX imports and local re-exports.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const ts = require(path.join(require('node:os').homedir(), '.local/share/mlx-server/code-intelligence/node_modules/typescript'));

function resolve(input) {
  const root = path.resolve(input.root), sourceRoot = path.join(root, 'frontend/src');
  const modules = new Map(), fingerprints = {};
  function safe(file) {
    file = path.resolve(file);
    if (!file.startsWith(sourceRoot + path.sep) || !/\.(tsx?|jsx?)$/.test(file)) return false;
    for (let current = file; current !== root; current = path.dirname(current)) {
      if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) return false;
    }
    return fs.existsSync(file) && fs.statSync(file).isFile() && fs.statSync(file).size <= 200000;
  }
  function relative(file, from) {
    if (!from?.startsWith('.')) return null;
    const base = path.resolve(path.dirname(file), from);
    return [base, base + '.ts', base + '.tsx', base + '.js', base + '.jsx',
      path.join(base, 'index.ts'), path.join(base, 'index.tsx')].find(safe) || null;
  }
  function moduleAt(file) {
    if (modules.has(file)) return modules.get(file);
    if (!safe(file)) return null;
    if (modules.size >= 48) throw new Error('Component import graph exceeds its bound');
    const text = fs.readFileSync(file, 'utf8');
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true,
      /\.[jt]sx$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    if (sf.parseDiagnostics.length) return null;
    fingerprints[path.relative(root, file)] = crypto.createHash('sha256').update(text).digest('hex');
    const data = { imports: new Map(), exports: new Map(), stars: [], declarations: new Map(), tags: [], shadows: new Set() };
    modules.set(file, data);
    for (const node of sf.statements) {
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) && !node.importClause?.isTypeOnly) {
        const from = node.moduleSpecifier.text, clause = node.importClause, bindings = clause?.namedBindings;
        if (clause?.name) data.imports.set(clause.name.text, { from, name: 'default' });
        if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements)
          if (!item.isTypeOnly) data.imports.set(item.name.text, { from, name: item.propertyName?.text || item.name.text });
        if (bindings && ts.isNamespaceImport(bindings)) data.imports.set(bindings.name.text, { from, name: '*' });
      }
      if (ts.isExportDeclaration(node) && !node.isTypeOnly) {
        const from = node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier) ? node.moduleSpecifier.text : null;
        if (node.exportClause && ts.isNamedExports(node.exportClause)) for (const item of node.exportClause.elements)
          if (!item.isTypeOnly) data.exports.set(item.name.text, { from, name: item.propertyName?.text || item.name.text });
        if (from && !node.exportClause) data.stars.push(from);
      }
      const exported = node.modifiers?.some(item => item.kind === ts.SyntaxKind.ExportKeyword);
      const isDefault = node.modifiers?.some(item => item.kind === ts.SyntaxKind.DefaultKeyword);
      if (exported && (ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.name)
        data.declarations.set(isDefault ? 'default' : node.name.text, node.name.text);
      if (exported && ts.isVariableStatement(node)) for (const item of node.declarationList.declarations)
        if (ts.isIdentifier(item.name)) data.declarations.set(item.name.text, item.name.text);
    }
    function bindingNames(name) {
      if (ts.isIdentifier(name)) data.shadows.add(name.text);
      else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name))
        for (const item of name.elements) if (ts.isBindingElement(item)) bindingNames(item.name);
    }
    function visit(node) {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) data.tags.push(node.tagName.getText(sf));
      if ((ts.isVariableDeclaration(node) || ts.isParameter(node) || ts.isFunctionDeclaration(node) ||
          ts.isFunctionExpression(node) || ts.isClassDeclaration(node) || ts.isClassExpression(node) ||
          ts.isEnumDeclaration(node)) && node.name) bindingNames(node.name);
      ts.forEachChild(node, visit);
    }
    visit(sf);
    return data;
  }
  function lookup(file, name, seen = new Set()) {
    const key = file + ':' + name;
    if (seen.has(key) || seen.size >= 16) return [];
    seen = new Set([...seen, key]);
    const data = moduleAt(file);
    if (!data) return [];
    if (data.declarations.has(name)) return [{ source: path.relative(root, file), export: data.declarations.get(name) }];
    const named = data.exports.get(name);
    if (named) {
      const binding = named.from ? named : data.imports.get(named.name);
      const target = binding && relative(file, binding.from);
      return target ? lookup(target, binding.name, seen) : [];
    }
    const candidates = data.stars.flatMap(from => {
      const target = relative(file, from);
      return target ? lookup(target, name, seen) : [];
    });
    return [...new Map(candidates.map(item => [item.source + ':' + item.export, item])).values()];
  }
  const source = path.resolve(root, input.source), current = moduleAt(source), ids = [];
  if (!current) return { components: [], source_fingerprints: fingerprints };
  for (const tag of new Set(current.tags)) {
    const [local, member, extra] = tag.split('.'), binding = current.imports.get(local);
    if (!binding || extra || (!!member !== (binding.name === '*'))) continue;
    // Without scope resolution, a shadowed JSX name cannot prove its import origin.
    if (current.shadows.has(local)) return { components: [], source_fingerprints: fingerprints };
    const target = relative(source, binding.from);
    if (!target) continue;
    const origins = lookup(target, member || binding.name);
    if (origins.length !== 1) continue;
    for (const item of input.catalog) if (item.source === origins[0].source && item.export === origins[0].export && !ids.includes(item.id)) ids.push(item.id);
  }
  return { components: ids, source_fingerprints: fingerprints };
}

try { console.log(JSON.stringify(resolve(JSON.parse(fs.readFileSync(0, 'utf8'))))); }
catch (error) { console.log(JSON.stringify({ components: [], error: String(error) })); }
