const path = require('node:path');
const fs = require('node:fs');
module.exports = async ({page, root}) => {
  if (!fs.existsSync(path.join(root, 'frontend/src/framework/RecordGrid.tsx'))) return;
  const {verify} = require(path.resolve(root, '../platform/tests/browser_record_grid_selection.cjs'));
  const result = await verify(page.context().browser(), root);
  if (!result.passed) throw new Error('Record grid selection fixture failed');
};
