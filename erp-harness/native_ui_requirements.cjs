const editor = require('./ui_editor_requirement.cjs');
const query = require('./ui_query_requirement.cjs');
const grid = require('./ui_grid_requirement.cjs');

module.exports.verify = async (page, criterion, requirement, blocked) => {
  if (typeof criterion.check !== 'object') return [];
  const { check } = criterion;
  const text = check.text || '';
  const op = check.op || '';

  if (!['visible', 'text', 'layout'].includes(op)) return [];

  let type = '';
  if (/remaining.*height|remaining.*space|나머지.*높이|나머지.*공간/i.test(requirement)) type = 'gridFill';
  else if (/(등록|신규|수정|register|create|edit)/i.test(requirement) && /(패널|폼|화면|panel|form|screen)/i.test(requirement)) type = 'editor';
  else if (/조회|검색|query|search/i.test(requirement)) type = 'query';

  if (!type) return [];

  let selector = check.selector;
  if (!selector) {
    selector = type === 'gridFill' ? (check.relation === 'above' ? check.right : check.left) : (type === 'editor' ? check.right : check.left);
  }

  const loc = page.locator(selector);
  const count = await loc.count();
  if (count !== 1 || !(await loc.first().isVisible())) throw new Error('Element not found');

  const el = loc.first();
  const tag = await el.evaluate(node => node.tagName);
  let targetLoc = el;

  if (['INPUT', 'BUTTON', 'SELECT', 'TEXTAREA'].includes(tag)) {
    const form = el.locator('xpath=ancestor::form[1]');
    if (await form.count() > 0) targetLoc = form;
  }

  const box = await targetLoc.boundingBox();
  const viewport = page.viewportSize();
  if (!box || !viewport) throw new Error('Cannot measure UI requirement');

  const target = { loc: targetLoc, box, viewport, selector };

  if (type === 'gridFill') return await grid(target);
  if (type === 'editor') return await editor(target, requirement);
  if (type === 'query') return await query(target, requirement, blocked);

  return [];
};
