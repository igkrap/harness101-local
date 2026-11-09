const ts = require(require('os').homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
const { bindingLabel } = require('./ast_binding_labels.cjs');

function validateInsert(code, label) {
    if (label.includes('JSX')) return;
    const sf = ts.createSourceFile('fragment.tsx', code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const diags = sf.parseDiagnostics;
    if (diags.length > 0)
        throw new Error(diags[0].messageText);
    const isForbidden = (n) => ts.isImportDeclaration(n) || ts.isImportEqualsDeclaration(n) ||
        ts.isExportDeclaration(n) || ts.isExportAssignment(n) ||
        n.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword || m.kind === ts.SyntaxKind.DefaultKeyword);
        const isForbiddenModule = (n) => ts.isExportAssignment(n) || (n.modifiers?.some(m => m.kind === ts.SyntaxKind.DefaultKeyword));
    if (label.includes('after imports')) {
        const walk = (n) => { if (isForbiddenModule(n)) throw new Error('Module slot rejects exports/defaults'); ts.forEachChild(n, walk); }; ts.forEachChild(sf, walk);
return;
}
    if (label.includes('function prologue') || label.includes('before return')) {
        const wrapper = ts.createSourceFile('f.tsx', `function __AST_SCOPE__(){\n${code}\n}`, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
        const func = wrapper.statements[0]; if (wrapper.parseDiagnostics.length > 0 || wrapper.statements.length !== 1) throw new Error('Invalid wrapper');
        if (!ts.isFunctionDeclaration(func) || func.name?.text !== '__AST_SCOPE__' || !func.body) {
            throw new Error('Must be a function declaration named __AST_SCOPE__');
        }
        func.body.statements.forEach(s => {
            
            if (ts.isReturnStatement(s))
                throw new Error('Use return JSX node');
        });
        const check = (n) => {
            if (isForbidden(n))
                throw new Error('function-body accepts local statements only; import belongs after imports and screen markup belongs in return JSX node');
            ts.forEachChild(n, check);
        };
        ts.forEachChild(func.body, check);
        return;
    }
    throw new Error('Unknown label');
}

function validateOpening(code) {
  const trimmed = code.trim();
  const parse = (src) => ts.createSourceFile('temp.tsx', src, ts.ScriptTarget.Latest, true);


  const sf1 = parse(`const __x=(${trimmed});`);
  let tag = '';
  ts.forEachChild(sf1, node => {
    if (ts.isVariableStatement(node)) {
      ts.forEachChild(node.declarationList, decl => {
        if (ts.isVariableDeclaration(decl) && decl.initializer && ts.isParenthesizedExpression(decl.initializer)) {
          ts.forEachChild(decl.initializer.expression, child => {
            if (ts.isJsxOpeningElement(child)) {
              tag = child.tagName.getText(sf1);
            }
          });
        }
      });
    }
  });

  if (!tag) throw new Error('No JSX opening element found');

  const sf2 = parse(`const __x=(${trimmed}</${tag}>);`);
  if (sf2.parseDiagnostics.length > 0) throw new Error('Invalid JSX opening tag syntax');
  const statements = sf2.statements;

  if (statements.length !== 1 || !ts.isVariableStatement(statements[0])) {
    throw new Error('Expected only one variable statement');
  }

  const decl = statements[0].declarationList.declarations[0];
  if (statements[0].declarationList.declarations.length !== 1 || !decl || !decl.initializer || !ts.isParenthesizedExpression(decl.initializer)) {
    throw new Error('Expected only the opening tag');
  }

  const expr = decl.initializer.expression;
  if (!ts.isJsxElement(expr)) {
    throw new Error('Expected JSX element');
  }

  if (expr.openingElement.getText(sf2) !== trimmed || expr.children.length > 0) {
    throw new Error('Expected only the opening tag; use return JSX node for structural changes');
  }

  return undefined;
}

function describe(node, sf, label) {
    let owner = 'module';
    let curr = node.parent;
    while (curr) {
      if (ts.isFunctionDeclaration(curr) && curr.name) {
        owner = curr.name.getText(sf);
        break;
      }
      if (ts.isVariableDeclaration(curr) && curr.name) {
        owner = curr.name.getText(sf);
        break;
      }
      if (ts.isPropertyDeclaration(curr) && curr.name) {
        owner = curr.name.getText(sf);
        break;
      }
      if (ts.isArrowFunction(curr) || ts.isFunctionExpression(curr)) {
        if (ts.isVariableDeclaration(curr.parent)) {
          owner = curr.parent.name.getText(sf);
          break;
        }
      }
      curr = curr.parent;
    }
    if (owner.length > 40) owner = owner.substring(0, 37) + '...';

    let role = label;
    if (ts.isImportDeclaration(node)) {
      role = 'module imports only';
    } else if (ts.isJsxElement(node) || ts.isJsxFragment(node) || ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      let eff = node;
      if (ts.isJsxOpeningElement(node)) {
        eff = node.parent;
      }
      const tag = ts.isJsxFragment(eff) ? 'Fragment' : (ts.isJsxElement(eff) ? eff.openingElement.tagName.getText(sf) : eff.tagName.getText(sf));
      let isReturn = false;
      let p = eff.parent;
      while (p && ts.isParenthesizedExpression(p)) p = p.parent;
      if (p && ts.isReturnStatement(p)) isReturn = true;

      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        role = (isReturn ? 'return JSX ' : 'JSX ') + tag + ' opening <' + tag + '> attributes only';
      } else {
        role = (isReturn ? 'return JSX ' : 'JSX ') + '<' + tag + '>';
      }
      if (ts.isJsxElement(node) && role.includes('opening')) {
        // Handled by logic above
      }
    }

    if (ts.isVariableStatement(node)) {
      const decl = node.declarationList.declarations[0];
      if (decl && decl.name.getText(sf) === 'meta') role = 'metadata meta only; NOT screen JSX';
    }

    role = bindingLabel(node, sf, role, ts);
    const start = sf.getLineAndCharacterOfPosition(node.getStart(sf));
    const end = sf.getLineAndCharacterOfPosition(node.getEnd(sf));
    const res = `${owner} ${start.line + 1}:${end.line + 1} ${role}`;
    return res.length > 150 ? res.substring(0, 147) + '...' : res;
  }

module.exports = { describe, validateInsert, validateOpening };
