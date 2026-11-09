const fs = require('fs');
const ts = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');

function patch(kind, source, styles) {
  if (source.length < 1 || source.length > 12000) throw new Error('Invalid source length');
  if (typeof styles !== 'object' || Array.isArray(styles)) throw new Error('Styles must be object');
  if (Object.keys(styles).length < 1 || Object.keys(styles).length > 16) throw new Error('Invalid style keys count');
  if (kind !== 'JsxElement' && kind !== 'JsxSelfClosingElement') throw new Error('Invalid kind');
  const prefix = 'const __style_target__=(';
  const wrapper = prefix + source + ');';
  const sf = ts.createSourceFile('style.tsx', wrapper, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (sf.parseDiagnostics.length > 0 || sf.statements.length !== 1) throw new Error('Invalid source');
  const stmt = sf.statements[0];
  if (!stmt || stmt.kind !== ts.SyntaxKind.VariableStatement) throw new Error('Invalid source');
  if (stmt.declarationList.declarations.length !== 1) throw new Error('Invalid source');
  const decl = stmt.declarationList.declarations[0];
  if (!decl || decl.initializer?.kind !== ts.SyntaxKind.ParenthesizedExpression) throw new Error('Invalid source');
  const expr = decl.initializer.expression;
  if (expr.kind !== (kind === 'JsxElement' ? ts.SyntaxKind.JsxElement : ts.SyntaxKind.JsxSelfClosingElement)) throw new Error('Kind mismatch');
  const opening = expr.kind === ts.SyntaxKind.JsxElement ? expr.openingElement : expr;
  const props = opening.attributes.properties;
  let styleAttr = null;
  for (const p of props) {
    if (p.kind === ts.SyntaxKind.JsxSpreadAttribute) throw new Error('Spread not allowed');
    if (p.name.getText(sf) === 'style') {
      if (styleAttr) throw new Error('Duplicate style');
      styleAttr = p;
    }
  }
  const keyRegex = /^(?:[A-Za-z][A-Za-z0-9]*|--[A-Za-z0-9-]+)$/;
  const newProps = [];
  for (const [k, v] of Object.entries(styles)) {
    if (!keyRegex.test(k) || k === 'constructor' || k === 'prototype' || k === '__proto__') throw new Error('Invalid key');
    if (v !== null && typeof v !== 'string' && typeof v !== 'number') throw new Error('Invalid value');
    if (typeof v === 'number' && !Number.isFinite(v)) throw new Error('Invalid value');
    if (typeof v === 'string' && (v.length > 500)) throw new Error('Value too long');
    newProps.push({ k, v });
  }
  const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed });
  const sameStyles = (existingProps) => {
    const map = new Map();
    for (const p of existingProps) {
      if (p.kind !== ts.SyntaxKind.PropertyAssignment) return false;
      const name = p.name?.text;
      if (!name || (p.kind === ts.SyntaxKind.PropertyAssignment && !p.initializer)) return false;
      map.set(name, p);
    }
    for (const { k, v } of newProps) {
      const p = map.get(k);
      if (v === null) {
        if (p) return false;
        continue;
      }
      if (!p) return false;
      const init = p.initializer;
      if (typeof v === 'string') {
        if (!ts.isStringLiteral(init) || init.text !== v) return false;
      } else {
        if (!ts.isNumericLiteral(init) || Number(init.text) !== v || !Number.isFinite(v)) return false;
      }
    }
    return true;
  };
  const buildObj = (existingProps) => {
    const factory = ts.factory;
    const finalProps = [];
    const styleKeys = new Set(newProps.map(p => p.k));
    for (const p of existingProps) {
      const name = p.name?.text;
      if ((p.kind === ts.SyntaxKind.PropertyAssignment || p.kind === ts.SyntaxKind.ShorthandPropertyAssignment) && styleKeys.has(name)) continue;
      finalProps.push(p);
    }
    for (const { k, v } of newProps) {
      if (v === null) continue;
      let valNode;
      if (typeof v === 'string') valNode = factory.createStringLiteral(v);
      else {
        if (!Number.isFinite(v)) throw new Error('Not finite');
        valNode = factory.createNumericLiteral(Math.abs(v));
        if (v < 0) valNode = factory.createPrefixUnaryExpression(ts.SyntaxKind.MinusToken, valNode);
      }
      finalProps.push(factory.createPropertyAssignment(factory.createStringLiteral(k), valNode));
    }
    return factory.createObjectLiteralExpression(finalProps);
  };

  let newAttrText;
  if (styleAttr) {
    const existingObj = styleAttr.initializer;
    if (existingObj?.kind !== ts.SyntaxKind.JsxExpression || existingObj.expression?.kind !== ts.SyntaxKind.ObjectLiteralExpression) throw new Error('Unsupported style');
    if (sameStyles(existingObj.expression.properties)) return source;
    const updatedObj = buildObj(existingObj.expression.properties);
    newAttrText = `style={${printer.printNode(ts.EmitHint.Expression, updatedObj, sf)}}`;
    const start = styleAttr.getStart(sf) - prefix.length;
    const end = styleAttr.getEnd(sf) - prefix.length;
    const result = source.slice(0, start) + newAttrText + source.slice(end);
    return result;
  } else {
    if (newProps.every(p => p.v === null)) return source;
    const updatedObj = buildObj([]);
    newAttrText = ` style={${printer.printNode(ts.EmitHint.Expression, updatedObj, sf)}}`;
    const insertPos = opening.attributes.end - prefix.length;
    const result = source.slice(0, insertPos) + newAttrText + source.slice(insertPos);
    return result;
  }
}

if (require.main === module) {
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { kind, source, styles } = input;
  if (Object.keys(styles).length > 16) throw new Error('Too many keys');
  const code = patch(kind, source, styles);
  const sfCheck = ts.createSourceFile('check.tsx', `const __style_target__=(${code});`, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (sfCheck.parseDiagnostics.length > 0) throw new Error('TSX error');
  process.stdout.write(JSON.stringify({ ok: true, code, changed: code !== source }) + '\n');
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, error: e.message }) + '\n');
  process.exit(1);
}

}

module.exports = { patch };
