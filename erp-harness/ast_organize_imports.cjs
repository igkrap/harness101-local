const fs = require('fs');
const path = require('path');
const os = require('os');
const ts = require(path.join(os.homedir(), '.local/share/mlx-server/code-intelligence/node_modules/typescript'));

function error(msg) {
  process.stdout.write(JSON.stringify({ error: msg }) + '\n');
  process.exit(1);
}

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { source, path: inputPath } = input;
  const filename = path.resolve(inputPath);

  const host = {
    getScriptFileNames: () => [filename],
    getScriptVersion: () => '0',
    getScriptSnapshot: (fileName) => {
      if (fileName === filename) {
        return ts.ScriptSnapshot.fromString(source);
      }
      const text = ts.sys.readFile(fileName);
      return text ? ts.ScriptSnapshot.fromString(text) : undefined;
    },
    getCurrentDirectory: () => path.dirname(filename),
    getDefaultLibFileName: (options) => ts.getDefaultLibFileName(options),
    fileExists: (fileName) => fileName === filename || ts.sys.fileExists(fileName),
    readFile: (fileName) => fileName === filename ? source : ts.sys.readFile(fileName),
    readDirectory: (dirName) => ts.sys.readDirectory(dirName),
    onError: () => {},
  };

  const options = {
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    jsx: ts.JsxEmit.React,
    allowJs: true,
    allowNonLocalization: true,
  };
  host.getCompilationSettings = () => options;

  const service = ts.createLanguageService(host);

  const sf = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const diags = sf.parseDiagnostics;
  if (diags.length > 0) throw new Error('Parse error');

  let boundary = source.length;
  for (let i = 0; i < sf.statements.length; i++) {
    if (sf.statements[i].kind !== ts.SyntaxKind.ImportDeclaration) {
      boundary = sf.statements[i].getStart(sf);
      break;
    }
  }

  if (sf.statements.some(stmt => ts.isImportDeclaration(stmt) && stmt.getStart(sf) >= boundary)) throw Error('Interleaved imports cannot be normalized safely');
  const sideEffects = [];
  for (const stmt of sf.statements) {
    if (stmt.kind === ts.SyntaxKind.ImportDeclaration) {
      if (!stmt.importClause) sideEffects.push(stmt.moduleSpecifier.text);
    } else break;
  }

  const changes = service.organizeImports({ type: 'file', fileName: filename }, {}, {});
  let newSource = source;
  const edits = [];
  for (const fc of changes) {
    if (path.resolve(fc.fileName) !== filename) continue;
    for (const tc of fc.textChanges) {
      if (tc.span.start < 0 || tc.span.length < 0 || tc.span.start + tc.span.length > boundary) continue;
      edits.push(tc);
    }
  }

  if (edits.length > 0) {
    edits.sort((a, b) => b.span.start - a.span.start);
    for (const e of edits) {
      const { start, length } = e.span;
      newSource = newSource.slice(0, start) + e.newText + newSource.slice(start + length);
    }

    const nsf = ts.createSourceFile(filename, newSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    if(nsf.parseDiagnostics.length) throw Error('Normalized parse error');
    let nBoundary = newSource.length;
    for (let i = 0; i < nsf.statements.length; i++) {
      if (nsf.statements[i].kind !== ts.SyntaxKind.ImportDeclaration) {
        nBoundary = nsf.statements[i].getStart(nsf);
        break;
      }
    }

    if (source.slice(boundary) !== newSource.slice(nBoundary)) throw new Error('Body mismatch');

    const nSideEffects = [];
    for (const stmt of nsf.statements) {
      if (stmt.kind === ts.SyntaxKind.ImportDeclaration) {
        if (!stmt.importClause) nSideEffects.push(stmt.moduleSpecifier.text);
      } else break;
    }
    if (JSON.stringify(sideEffects) !== JSON.stringify(nSideEffects)) throw new Error('Side effects mismatch');

    if (newSource !== source) {
      process.stdout.write(JSON.stringify({ source: newSource, changed: newSource !== source }) + '\n');
      process.exit(0);
    }
  }

  process.stdout.write(JSON.stringify({ source, changed: false }) + '\n');
} catch (e) {
  error(e.message);
} finally {
  // service is garbage collected
}
