const fs = require('fs');
const os = require('os');
const ts = require(os.homedir() + '/.local/share/mlx-server/code-intelligence/node_modules/typescript');
const {describe} = require('./ast_scope_rules.cjs');
const {eligibleNestedHandler,eligibleHandlerStatement} = require('./ast_handler_scopes.cjs');

let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
    try {
        const raw = JSON.parse(input);
        const { path: filePath, source } = raw;
        const kind = filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : filePath.endsWith('.jsx') ? ts.ScriptKind.JSX : filePath.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS;
        const sf = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, kind);
        
        const diagnostics = sf.parseDiagnostics.map(d => ({
            message: ts.flattenDiagnosticMessageText(d.messageText, '\n'),
            line: sf.getLineAndCharacterOfPosition(d.start || 0).line + 1,
            column: sf.getLineAndCharacterOfPosition(d.start || 0).character + 1
        }));

        const nodes = [];
        let totalSource = 0;
        const slots = [];
        const seenPositions = new Set();
        const seenNodes = new Set();

        const getByteOffset = (pos) => Buffer.byteLength(source.slice(0, pos), 'utf8');

        const addSlot = (pos, label) => {
            if (slots.length >= 40) return;
            if (seenPositions.has(pos)) return;
            seenPositions.add(pos);
            slots.push({ id: `s${slots.length}`, kind: 'insert', label, start: getByteOffset(pos), end: getByteOffset(pos), source: '' });
        };

        const addNode = (node, label) => {
            if (nodes.length >= 100) return;
            const start = node.getStart(sf);
            const end = node.getEnd(sf);
            const text = source.slice(start, end);
            const limit = (node.kind === ts.SyntaxKind.JsxElement || node.kind === ts.SyntaxKind.JsxSelfClosingElement || node.kind === ts.SyntaxKind.JsxFragment) ? 12000 : 3000;
            if (text.length > limit || seenNodes.has(`${start}-${end}`)) return;
            
            const parent = node.parent;
            const forbidden = [ts.SyntaxKind.SourceFile, ts.SyntaxKind.FunctionDeclaration, ts.SyntaxKind.ClassDeclaration, ts.SyntaxKind.Block];
            const handler = raw.allow_nested_handlers === true && eligibleNestedHandler(node, sf);
            if (forbidden.includes(node.kind) && !handler) return;

            if (totalSource + text.length > 32000) return;
            seenNodes.add(`${start}-${end}`);
            nodes.push({
                id: `n${nodes.length}`,
                kind: ts.isVariableStatement(node) ? 'VariableStatement' : ts.SyntaxKind[node.kind],
                label: describe(node, sf, handler ? `nested handler function ${node.name.text}; preserve name/parameters; async/body only` : label),
                ...(handler ? {handler_scope: true} : {}),
                ...(raw.allow_nested_handlers === true && eligibleHandlerStatement(node) ? {handler_statement_scope: true} : {}),
                start: getByteOffset(start),
                end: getByteOffset(end),
                source: text
            });
            totalSource += text.length;
        };

        let lastImportEnd = 0;
        ts.forEachChild(sf, child => {
            if (child.kind === ts.SyntaxKind.ImportDeclaration) {
                lastImportEnd = child.getEnd(sf);
                addNode(child, 'import declaration');
            } else if (child.kind === ts.SyntaxKind.FunctionDeclaration || child.kind === ts.SyntaxKind.VariableStatement || 
                       child.kind === ts.SyntaxKind.InterfaceDeclaration || child.kind === ts.SyntaxKind.TypeAliasDeclaration) {
                addNode(child, ts.SyntaxKind[child.kind]);
            }
        });
        addSlot(lastImportEnd, 'after imports');

        const jsxOpeningPass = (node) => {
            if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
                addNode(node, 'JSX opening tag');
            }
            ts.forEachChild(node, jsxOpeningPass);
        };
        jsxOpeningPass(sf);

        const priorityPass = (node) => {
            if (ts.isReturnStatement(node)) {
                let expr = node.expression;
                while (expr && expr.kind === ts.SyntaxKind.ParenthesizedExpression) expr = expr.expression;
                if (expr && (ts.isJsxElement(expr) || ts.isJsxFragment(expr) || ts.isJsxSelfClosingElement(expr))) {
                    addNode(expr, 'return JSX layout root');
                }
            }
            ts.forEachChild(node, priorityPass);
        };
        priorityPass(sf);

        const namedRegionPass = (node) => {
            if (ts.isJsxElement(node)) {
                const attrs = node.openingElement.attributes.properties;
                const isNamed = attrs.some(attr => ts.isJsxAttribute(attr) && (attr.name.getText(sf) === 'data-testid' || attr.name.getText(sf) === 'id'));
                if (isNamed) addNode(node, 'named layout region');
            }
            ts.forEachChild(node, namedRegionPass);
        };
        namedRegionPass(sf);

        const traverse = (node) => {
            if (node.kind === ts.SyntaxKind.FunctionDeclaration && node.body) {
                const name = node.name ? node.name.getText(sf) : 'anon';
                addSlot(node.body.getStart(sf) + 1, `${name} function prologue; local statements only; no imports/exports or whole-screen code`);
                
                let bodyStmt = node.body.statements;
                bodyStmt.forEach(stmt => {
                    if (stmt.kind !== ts.SyntaxKind.ReturnStatement) {
                        addNode(stmt, 'body statement');
                    } else {
                        addSlot(stmt.getStart(sf), `${name} before return; local statements only; no imports/exports or whole-screen code`);
                        let expr = stmt.expression;
                        while (expr && expr.kind === ts.SyntaxKind.ParenthesizedExpression) expr = expr.expression;
                        if (expr && (ts.isJsxElement(expr) || ts.isJsxFragment(expr))) {
                            expr.children.forEach(child => {
                                if (ts.isJsxElement(child) || ts.isJsxFragment(child) || ts.isJsxSelfClosingElement(child)) {
                                    addNode(child, 'layout region');
                                }
                            });
                            const closing = ts.isJsxElement(expr) ? expr.closingElement.getStart(sf) : expr.closingFragment.getStart(sf);
                            addSlot(closing, `${name} append JSX children INSIDE <${expr.openingElement ? expr.openingElement.tagName.getText(sf) : 'fragment'}> BEFORE closing tag`);
                        }
                    }
                });
            }
            if (node.kind === ts.SyntaxKind.JsxElement || node.kind === ts.SyntaxKind.JsxSelfClosingElement || node.kind === ts.SyntaxKind.JsxFragment) {
                addNode(node, ts.SyntaxKind[node.kind]);
            }
            ts.forEachChild(node, traverse);
        };
        traverse(sf);

        const catalog = [...slots, ...nodes].slice(0, 100);
        catalog.forEach(item => {
            if (item.kind === 'JsxOpeningElement') {
                const full = catalog.find(n => n.kind === 'JsxElement' && n.start === item.start);
                if (full) item.label += '; complete JSX node ' + full.id;
            }
        });
        console.log(JSON.stringify({ engine: 'typescript-ast', nodes: catalog, diagnostics }));
    } catch (e) {
        console.log(JSON.stringify({ error: e.message }));
        process.exit(1);
    }
});
