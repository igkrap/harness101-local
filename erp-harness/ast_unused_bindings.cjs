// Remove unused destructured function-parameter properties (TS6133) using TypeScript's own codefix.
// Safety: only BindingElements of an ObjectBindingPattern that is a function parameter, only literal/absent
// defaults (no side effects), and every change must stay inside that pattern.
const fs = require('fs');
const path = require('path');
const os = require('os');
const ts = require(path.join(os.homedir(), '.local/share/mlx-server/code-intelligence/node_modules/typescript'));

function out(value, code = 0) { process.stdout.write(JSON.stringify(value) + '\n'); process.exit(code); }

try {
  const { source, path: inputPath } = JSON.parse(fs.readFileSync(0, 'utf8'));
  const filename = path.resolve(inputPath);
  const options = { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
    noUnusedLocals: true, noUnusedParameters: true, strict: true, skipLibCheck: true, moduleResolution: ts.ModuleResolutionKind.Bundler };
  let text = source;
  let version = 0;
  const host = {
    getScriptFileNames: () => [filename], getScriptVersion: () => String(version),
    getScriptSnapshot: f => f === filename ? ts.ScriptSnapshot.fromString(text) : (ts.sys.readFile(f) ? ts.ScriptSnapshot.fromString(ts.sys.readFile(f)) : undefined),
    getCurrentDirectory: () => path.dirname(filename), getCompilationSettings: () => options,
    getDefaultLibFileName: o => ts.getDefaultLibFilePath(o), fileExists: f => f === filename || ts.sys.fileExists(f),
    readFile: f => f === filename ? text : ts.sys.readFile(f), readDirectory: ts.sys.readDirectory, directoryExists: ts.sys.directoryExists,
    getDirectories: ts.sys.getDirectories,
  };
  const service = ts.createLanguageService(host);
  const removed = [];
  for (let pass = 0; pass < 8; pass++) {
    const sf = service.getProgram().getSourceFile(filename);
    if (!sf || sf.parseDiagnostics.length) throw new Error('Parse error');
    const diagnostics = service.getSemanticDiagnostics(filename).filter(d => d.code === 6133 && d.start !== undefined);
    let applied = false;
    for (const d of diagnostics) {
      let node = ts.getTokenAtPosition ? ts.getTokenAtPosition(sf, d.start) : null;
      if (!node) continue;
      const element = node.parent;
      if (!element || !ts.isBindingElement(element) || element.name !== node) continue;
      const pattern = element.parent;
      if (!ts.isObjectBindingPattern(pattern) || !ts.isParameter(pattern.parent)) continue;
      const init = element.initializer;
      if (init && !(ts.isLiteralExpression(init) || init.kind === ts.SyntaxKind.TrueKeyword || init.kind === ts.SyntaxKind.FalseKeyword
          || init.kind === ts.SyntaxKind.NullKeyword || (ts.isPrefixUnaryExpression(init) && ts.isNumericLiteral(init.operand)))) continue;
      const fixes = service.getCodeFixesAtPosition(filename, d.start, d.start + d.length, [6133], {}, {});
      const fix = fixes.find(f => f.fixName === 'unusedIdentifier' && f.changes.every(c => path.resolve(c.fileName) === filename
        && c.textChanges.every(t => t.span.start >= pattern.getStart(sf) && t.span.start + t.span.length <= pattern.getEnd())));
      if (!fix) continue;
      const edits = fix.changes.flatMap(c => c.textChanges).sort((a, b) => b.span.start - a.span.start);
      let next = text;
      for (const e of edits) next = next.slice(0, e.span.start) + e.newText + next.slice(e.span.start + e.span.length);
      // Everything outside the parameter pattern must be byte-identical.
      const start = pattern.getStart(sf), end = pattern.getEnd(), delta = next.length - text.length;
      if (next.slice(0, start) !== text.slice(0, start) || next.slice(end + delta) !== text.slice(end)) continue;
      removed.push(node.text);
      text = next; version++; applied = true;
      break;
    }
    if (!applied) break;
  }
  const check = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (check.parseDiagnostics.length) throw new Error('Result parse error');
  out({ source: text, changed: text !== source, removed });
} catch (e) {
  out({ error: e.message }, 1);
}
