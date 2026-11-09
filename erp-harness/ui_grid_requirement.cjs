module.exports = async function(target) {
  const { loc, box, viewport, selector } = target;
  const isSelf = await loc.evaluate(el => el.matches('table, [role="grid"], [role="table"]'));
  const count = await loc.locator('table, [role="grid"], [role="table"]').count() + (isSelf ? 1 : 0);
  const available = viewport.height - box.y;
  if (count < 1) throw new Error('결과 그리드가 없습니다.');
  if (available <= 0 || box.height < 0.65 * available || box.y + box.height < viewport.height - 96 || box.y + box.height > viewport.height + 24) {
    const chain = await loc.evaluate(el => {
      const items = [];
      let curr = el;
      for (let i = 0; i < 7 && curr; i++) {
        const box = curr.getBoundingClientRect();
        const style = window.getComputedStyle(curr);
        items.push({
          tag: curr.tagName.toLowerCase(),
          id: curr.id,
          testid: curr.getAttribute('data-testid'),
          className: curr.className.toString().substring(0, 120),
          height: box.height,
          y: box.y,
          display: style.display,
          flex: style.display === 'flex',
          flexDirection: style.flexDirection,
          minHeight: style.minHeight,
          heightStyle: curr.style.height,
          overflow: style.overflow
        });
        curr = curr.parentElement;
      }
      return items;
    });
    throw new Error(`그리드 높이 부족: actual_height=${box.height}, top=${box.y}, actual_bottom=${box.y+box.height}, viewport_height=${viewport.height}, allowed_height_min=${Math.max(0,0.65*available,viewport.height-96-box.y)}, allowed_height_max=${Math.max(0,viewport.height+24-box.y)}, recommended_height=${Math.max(0,viewport.height-box.y-24)}. Existing ancestors=${JSON.stringify(chain)}. (Tip: Grid height must be bounded by a responsive parent layout; ensure ancestors have fixed or constrained heights rather than expanding to content.)`);
  }
  return [{ kind: 'remaining_grid_height', selector, box, viewport, tables: count }];
};
