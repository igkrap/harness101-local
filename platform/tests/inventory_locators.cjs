// Resolve controls by behavior and accessible labels, independently of generated test IDs.
function inventoryLocators(page) {
  const query = page.locator('form[data-ui="query-panel"]:visible').or(page.locator('form:visible').filter({
    has: page.getByRole('button', { name: /^(조회|검색)$/ }),
  }));
  const form = page.locator('form:visible:not([data-ui="query-panel"])').filter({
    has: page.getByLabel(/^최소\s*수량/),
  }).filter({ hasNot: page.getByRole('button', { name: /^(조회|검색)$/ }) });
  const grid = page.locator('table:visible, [role="grid"]:visible, [role="table"]:visible');
  const reset = page.getByRole('button', { name: /^(신규( 등록)?|새로 (등록|만들기)|새 항목|초기화|취소)$/ });
  return { query, form, grid, reset };
}
async function formAction(page, form, name) {
  const internal = form.getByRole('button', { name });
  if (await internal.count()) return internal;
  const id = await form.getAttribute('id');
  if (!id) throw new Error('Form has no internal action or ID for an external action');
  return page.locator(`button[form=${JSON.stringify(id)}]:visible`).filter({ hasText: name });
}
module.exports = { inventoryLocators, formAction };
