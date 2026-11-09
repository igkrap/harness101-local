module.exports = async function check(ctx) {
  if (!ctx.fs.existsSync(ctx.path.join(ctx.frontend, 'src/framework/index.ts'))) return;
  const {verify} = require(ctx.path.resolve(ctx.root, '../platform/tests/browser_record_panels.cjs'));
  const result = await verify(ctx.page.context().browser(), ctx.root);
  ctx.assert.equal(result.passed, true);
};
