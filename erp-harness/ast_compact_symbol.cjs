module.exports.compactSymbol = function compactSymbol(ts, sf, node) {
  const printer = ts.createPrinter({
    removeComments: true
  });

  const emit = printer.printNode(
    ts.EmitHint.Unspecified,
    node,
    sf
  );

  return emit;
};
