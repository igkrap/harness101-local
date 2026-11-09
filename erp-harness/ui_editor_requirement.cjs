module.exports = async function(target, requirement) {
  const { loc, box, viewport, selector } = target;
  const forms = (await loc.locator('form').count()) + (await loc.evaluate(el => el.tagName === 'FORM' ? 1 : 0));
  const inputs = await loc.locator('input:visible, select:visible, textarea:visible').count();
  const buttons = await loc.getByRole('button', { name: /추가|등록|저장|수정|save|create|register|update/i }).count();

  if (forms < 1 || inputs < 1 || buttons < 1) {
    throw new Error(`요소 부족: form(${forms}), input(${inputs}), button(${buttons})`);
  }

  if (/우측|right/i.test(requirement) && box.x < viewport.width / 2) {
    throw new Error('요소가 우측에 위치해야 합니다.');
  }

  const eligible = loc.locator('input:not([type]):visible, input[type="text"]:visible, input[type="search"]:visible, textarea:visible').first();
  let input_state_verified = false;
  if (await eligible.count() > 0) {
    if (!(await eligible.isEditable())) throw new Error('editor_input_not_editable');
    const original = await eligible.inputValue();
    const probe = '__harness_editor_probe__';
    try {
      await eligible.fill(probe);
      await loc.page().waitForTimeout(30);
      if ((await eligible.inputValue()) !== probe) throw new Error('editor_input_not_retained: connect editable input to form state; static value with no-op onChange is not a working editor.');
      input_state_verified = true;
    } finally {
      if (await eligible.isEditable()) await eligible.fill(original);
    }
  }
  return [{ kind: 'editor_controls', selector, forms, inputs, buttons, box, input_state_verified }];
};
