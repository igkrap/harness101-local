module.exports.bindingLabel = function bindingLabel(node, sf, role, ts) {
  if (!ts.isVariableStatement(node)) {
    return role;
  }

  const names = node.declarationList.declarations
    .map(d => d.name.getText(sf))
    .join(', ');

  return role + ' [bindings: ' + names + ']';
};
