module.exports = async function(target, requirement, blocked) {
  const loc = target.loc;
  const controls = loc.locator('input:visible, select:visible, textarea:visible');
  const n = await controls.count();
  const name = /조회|검색|search|query/i;
  let btn = loc.getByRole('button', { name });
  if (await btn.count() === 0) {
    // A shared header toolbar may run the query: its button submits the query form by form id.
    const formId = await loc.evaluate(el => ((el.matches('form') ? el : el.querySelector('form')) || {}).id || '');
    if (formId) btn = loc.page().locator(`button[form="${formId.replace(/"/g, '\\"')}"]`).filter({ hasText: name });
  }

  if (n < 1 || await btn.count() !== 1) throw new Error('조회 입력과 조회 버튼 하나가 필요합니다.');
  {
    const isEnabled = await btn.isEnabled();
    if (!isEnabled) throw new Error('조회 버튼이 비활성 상태입니다.');
    const text = await btn.innerText();
    if (/추가|등록|저장|수정|create|register|save|update/i.test(text)) {
      throw new Error('조회와등록버튼분리필요');
    }

    const heights = [];
    const tops = [];
    for (let i = 0; i < n; i++) {
      const box = await controls.nth(i).boundingBox();
      if (box) {
        heights.push(box.height);
        tops.push({y: box.y, h: box.height});
      }
    }
    heights.sort((a, b) => a - b);
    const median = heights.length > 0 ? heights[Math.floor(heights.length / 2)] : 0;
    const twoRows = /2\s*줄|두\s*줄|two\s*(rows|lines)/i.test(requirement);
    let max = Infinity;
    if (twoRows) {
      tops.sort((a, b) => a.y - b.y);
      const groups = [];
      for (const t of tops) {
        if (groups.length === 0 || t.y - groups[groups.length - 1].lastY > Math.max(4, median / 2)) {
          groups.push({lastY: t.y, count: 1});
        } else {
          groups[groups.length - 1].count++;
          groups[groups.length - 1].lastY = t.y;
        }
      }
      if (groups.length > 2) throw new Error('query_rows_exceeded: measured=' + groups.length + ', max=2');
      const pitch = groups.length === 2 ? groups[1].lastY - groups[0].lastY : 0;
      max = Math.max(2 * median + 96, 2 * pitch + 64);
    }
    if (target.box.height > max) throw new Error(`height_exceeded: measured=${target.box.height}, max=${max}, median=${median}, selector=${target.selector}. Hint: reduce query-only controls/padding; registration fields belong in editor panel.`);

    const allControls = loc.locator('input:visible, select:visible, textarea:visible, button:visible');
    const controlCount = await allControls.count();
    for (let i = 0; i < controlCount; i++) {
      const c = allControls.nth(i);
      const box = await c.boundingBox();
      if (box) {
        if (box.y < target.box.y - 2 || box.x < target.box.x - 2 || box.y + box.height > target.box.y + target.box.height + 2 || box.x + box.width > target.box.x + target.box.width + 2) {
          throw new Error('query_controls_overflow: ' + JSON.stringify({region: target.box, control: box, text: await c.getAttribute('aria-label') || await c.getAttribute('name') || await c.innerText()}) + ' hint: Reduce query-only contents or padding; do not shrink container over its controls. Registration form belongs in separate editor panel.');
        }
      }
    }

    for (let i = 0; i < n; i++) {
      const ctrl = controls.nth(i);
      const tag = await ctrl.evaluate(el => el.tagName.toLowerCase());
      const isReadonly = await ctrl.evaluate(el => el.readOnly || el.disabled);
      const isFile = await ctrl.evaluate(el => el.type === 'file');
      const isPass = await ctrl.evaluate(el => el.type === 'password');

      if (isReadonly || isFile || isPass) continue;

      const isReq = await ctrl.evaluate(el => el.getAttribute('required') !== null);
      const val = await ctrl.inputValue();

      if (isReq && !val) {
        if (tag === 'select') {
          await ctrl.selectOption({ index: 1 }); // Try second option if first is placeholder
        } else {
          const type = await ctrl.evaluate(el => el.type);
          if (type === 'number') await ctrl.fill((await ctrl.evaluate(el => el.min || '1')).replace(/\D/g, ''));
          else if (type === 'email') await ctrl.fill('probe@example.invalid');
          else if (type === 'date') await ctrl.fill('2026-01-01');
          else await ctrl.fill('__harness_probe__');
        }
      }
    }

    const isValid = await btn.evaluate(el => !el.form || el.form.checkValidity());
    if (!isValid) throw new Error('조회조건의필수값을채워야조회실행가능');

    const blockedLen = blocked.length;
    await btn.click();
    await loc.page().waitForLoadState('networkidle', { timeout: 5000 });

    const currentBlocked = blocked.length; // This logic assumes blocked is a proxy/tracker
    // Note: In real Playwright, we'd intercept requests. Here we follow the prompt's logic.
    // If the caller's 'blocked' list grew, it implies a write occurred.
    // Since we can't mutate the caller's array directly to detect changes without a proxy, 
    // we assume the requirement implies checking if the count changed.
    // However, the prompt says "If new blocked requests throw Error".
    // We will simulate the check by checking if the length increased.
    // (In a real test environment, 'blocked' would be a list of intercepted URLs).

    if (currentBlocked > blockedLen) throw new Error('readonlyqueryattemptedwrite');
    if (!(await btn.isVisible())) throw new Error('button_hidden_after_query');

    return [{
      kind: 'query_controls',
      selector: target.selector,
      inputs: n,
      buttonlabel: text,
      height: target.box.height,
      maxHeight: max
    }];
  }
};
