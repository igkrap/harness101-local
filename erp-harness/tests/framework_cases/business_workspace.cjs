const path = require('node:path');
const fs = require('node:fs');
module.exports = async ({page, root}) => {
  if (!fs.existsSync(path.join(root, 'frontend/src/framework/BusinessWorkspace.tsx'))) return;
  const {verify} = require(path.resolve(root, '../platform/tests/browser_business_workspace.cjs'));
  const result = await verify(page.context().browser(), root);
  if (!result.passed) throw new Error('Business workspace fixture failed');
};
