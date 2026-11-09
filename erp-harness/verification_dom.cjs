/**
 * verification_dom.cjs
 */

async function inspect(page) {
  const nodes = await page.locator('main,aside,nav,form,table,[role=grid],[role=table],[data-testid],input,button').evaluateAll((elements) => {
    return elements.slice(0, 100).map(el => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden' || style.display === 'none') return null;
      return {
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role'),
        testid: el.getAttribute('data-testid'),
        text: el.innerText?.slice(0, 100),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        display: style.display,
        flexDirection: style.flexDirection,
        gridTemplateColumns: style.gridTemplateColumns,
        overflow: style.overflow
      };
    }).filter(n => n !== null);
  });

  return {
    url: page.url(),
    title: await page.title(),
    nodes
  };
}

async function run(page, check) {
  // Visible to a user: non-empty box, not hidden by style, and not clipped away by an ancestor with
  // overflow hidden/clip (e.g. a control inside a panel collapsed to height 0).
  const reallyVisible = (el) => {
    let r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return false;
    let box = { l: r.left, t: r.top, r: r.right, b: r.bottom };
    for (let a = el.parentElement; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
      if (/(hidden|clip|auto|scroll)/.test(cs.overflow + cs.overflowX + cs.overflowY)) {
        const ar = a.getBoundingClientRect();
        box = { l: Math.max(box.l, ar.left), t: Math.max(box.t, ar.top), r: Math.min(box.r, ar.right), b: Math.min(box.b, ar.bottom) };
        if (box.r - box.l < 1 || box.b - box.t < 1) return false;
      }
    }
    return true;
  };
  const resolveLocator = async (selector) => {
    // A user can only act on what is visible: hidden or clipped matches (e.g. a control inside a
    // collapsed panel) do not make a selector ambiguous. Several really visible matches still do.
    const all = page.locator(selector);
    const deadline = Date.now() + 5000;
    let shown = [];
    while (Date.now() < deadline) {
      shown = await all.evaluateAll((els, fn) => els.map((el, i) => (new Function('return ' + fn)())(el) ? i : -1).filter(i => i >= 0), reallyVisible.toString());
      if (shown.length) break;
      await page.waitForTimeout(100);
    }
    if (shown.length === 0) { await all.first().waitFor({ state: 'visible', timeout: 1 }); throw new Error(`no visible match for ${selector}`); }
    if (shown.length !== 1) throw new Error(`clearambiguityerror: expected 1 visible, found ${shown.length} for ${selector}`);
    return all.nth(shown[0]);
  };

  const retryMatch = async (fn, target, timeout = 5000) => {
    const start = Date.now();
    let lastVal;
    while (Date.now() - start < timeout) {
      lastVal = await fn();
      if (typeof target === 'string' ? lastVal.includes(target) : lastVal === target) return lastVal;
      await page.waitForTimeout(50);
    }
    throw new Error(`Value mismatch: expected ${target}, observed ${lastVal}`);
  };

  try {
    if (check.op === 'count') {
      // How many elements each selector matches right now (contract selector validation).
      const counts = {}, visible = {};
      for (const sel of check.selectors || []) {
        try {
          counts[sel] = await page.locator(sel).count();
          visible[sel] = await page.locator(sel).evaluateAll((els, fn) => els.filter(el => (new Function('return ' + fn)())(el)).length, reallyVisible.toString());
        } catch (e) { counts[sel] = -1; visible[sel] = -1; }
      }
      return { status: 'passed', reason: '', evidence: { counts, visible } };
    }

    if (check.op === 'inventory') {
      // Selector-relevant attributes of what is actually on the opened screen (for contract feedback).
      const items = await page.locator('[role],[aria-label],[data-ui],[data-testid],[data-region],button,form,table,input,select,textarea').evaluateAll(els => els.slice(0, 400).map(el => {
        const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
        const pick = n => el.getAttribute(n);
        const text = (el.tagName === 'BUTTON' ? (el.innerText || '').trim().slice(0, 30) : '');
        // Form fields usually lack name/stable id; address them by their label within their form.
        let field = null;
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) && el.labels && el.labels[0]) {
          const name = (el.labels[0].innerText || '').split('\n')[0].trim();
          const form = el.form && el.form.id ? '#' + el.form.id + ' >> ' : '';
          if (name) field = `${form}internal:label="${name.replace(/"/g, '\\"')}"i`;
        }
        const stableId = el.id && !/^_r_|^:r/.test(el.id) ? el.id : null;
        return { tag: el.tagName.toLowerCase(), role: pick('role'), label: pick('aria-label'), ui: pick('data-ui'), testid: pick('data-testid'), region: pick('data-region'), id: stableId, text, field, visible };
      }).filter(x => x.visible && (x.role || x.label || x.ui || x.testid || x.region || x.id || x.text || x.field)));
      // Fields inside inactive tabs are not on screen until their tab is opened: open each tab once
      // and record which fields it holds, then restore the originally selected tab.
      const tabs = [];
      const tabLoc = page.getByRole('tab');
      const tabCount = Math.min(await tabLoc.count(), 12);
      let original = null;
      for (let i = 0; i < tabCount; i++) if (await tabLoc.nth(i).getAttribute('aria-selected') === 'true') original = i;
      for (let i = 0; i < tabCount; i++) {
        const tab = tabLoc.nth(i);
        if (i === original || !(await tab.isVisible().catch(() => false))) continue;
        const name = ((await tab.innerText().catch(() => '')) || '').trim();
        await tab.click({ timeout: 2000 }).catch(() => null);
        await page.waitForTimeout(150);
        const fields = await page.locator('input,select,textarea').evaluateAll(els => els.filter(el => {
          const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && el.labels && el.labels[0];
        }).map(el => (el.labels[0].innerText || '').split('\n')[0].trim()).filter(Boolean));
        if (name) tabs.push({ tab: name, fields: [...new Set(fields)] });
      }
      if (original !== null) await tabLoc.nth(original).click({ timeout: 2000 }).catch(() => null);
      const shown = new Set(items.filter(x => x.field).map(x => (x.field.match(/label="(.*)"i$/) || [])[1]));
      for (const t of tabs) t.fields = t.fields.filter(f => !shown.has(f));
      return { status: 'passed', reason: '', evidence: { elements: items.slice(0, 120), tabs: tabs.filter(t => t.fields.length) } };
    }

    if (check.op === 'absent') {
      // Removed or no longer shown. The gate only accepts this op when the selector matched before the change.
      const all = page.locator(check.selector);
      await all.first().waitFor({ state: 'hidden', timeout: 5000 });
      return { status: 'passed', reason: '', evidence: { selector: check.selector, count: await all.count() } };
    }

    if (check.op === 'visible') {
      const loc = await resolveLocator(check.selector);
      const box = await loc.boundingBox();
      if (!box || box.width <= 0 || box.height <= 0) throw new Error('not visible');
      return { status: 'passed', reason: '', evidence: { selector: check.selector, box } };
    }

    if (check.op === 'text') {
      const loc = await resolveLocator(check.selector);
      const val = await retryMatch(async () => (await loc.innerText()), check.contains);
      return { status: 'passed', reason: '', evidence: { text: val } };
    }

    if (check.op === 'layout') {
      const a = await (await resolveLocator(check.left)).boundingBox();
      const b = await (await resolveLocator(check.right)).boundingBox();
      if (!a || !b || a.width <= 0 || a.height <= 0 || b.width <= 0 || b.height <= 0) throw new Error('null or zero box');
      
      let passed = false;
      if (check.relation === 'left_of') passed = a.x + a.width <= b.x + 2;
      else if (check.relation === 'above') passed = a.y + a.height <= b.y + 2;
      else if (check.relation === 'wider_than') passed = a.width > b.width * (check.ratio || 1);

      if (!passed) throw new Error(`layout failed: ${check.relation} comparison. Measured: ${JSON.stringify({a,b})}`);
      return { status: 'passed', reason: '', evidence: { a, b, ratio: check.ratio || 1 } };
    }

    if (check.op === 'scenario') {
      if (!check.steps.some(s => s.action.startsWith('expect_'))) throw new Error('scenario must have >=1 expect action');
      const evidence = [];
      const hiddenSoFar = [];
      const remembered = {};
      const diagnose = async (step) => {
        // Structural reason a step's target is missing: absent from the DOM, or present but inside an
        // element an earlier step proved hidden (so it disappeared together with it).
        try {
          const count = await page.locator(step.selector).count();
          if (count === 0) return `target ${step.selector} does not exist in the DOM at this point`;
          for (const h of hiddenSoFar) {
            if (await page.locator(h).locator(step.selector).count()) {
              return `target ${step.selector} exists (${count}) but is INSIDE ${h}, which an earlier step hid, so it is not visible; a control needed after hiding must stay outside the hidden element`;
            }
          }
          const loc = page.locator(step.selector).first();
          if (count > 1 && !['click', 'fill', 'select'].includes(step.action)) return `target ${step.selector} matches ${count} elements`;
          if (count > 1) return `target ${step.selector} matches ${count} elements; an action needs exactly one, narrow the selector`;
          if (await loc.isVisible() && ['click', 'fill', 'select'].includes(step.action)) {
            const state = await loc.evaluate(el => ({
              disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
              covered: (() => { const r = el.getBoundingClientRect(); const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return top && top !== el && !el.contains(top) ? (top.tagName.toLowerCase() + (top.id ? '#' + top.id : '')) : ''; })(),
            }));
            if (state.disabled) return `target ${step.selector} is visible but DISABLED at this step (disabled/aria-disabled), so it cannot be clicked; check what disables it after the previous steps`;
            if (state.covered) return `target ${step.selector} is visible but covered by <${state.covered}>, so the click cannot reach it`;
            return `target ${step.selector} is visible and enabled; the action itself failed`;
          }
          return `target ${step.selector} exists (${count}) but is not visible`;
        } catch (e) { return ''; }
      };
      let preAnimation = null;
      for (let index = 0; index < check.steps.length; index++) {
       const step = check.steps[index];
       try {
        const following = check.steps[index + 1];
        if (step.action === 'click' && following && following.action === 'expect_animated') {
          // Size before the click, so a change that happens inside the click's own render is seen.
          const probe = page.locator(following.selector).first();
          preAnimation = await probe.count() ? await probe.evaluate(el => ({ h: Math.round(el.getBoundingClientRect().height * 10) / 10,
            o: Math.round(parseFloat(getComputedStyle(el).opacity) * 100) / 100 })).catch(() => null) : null;
        }
        if (step.action === 'expect_hidden') {
          // Hidden means absent or not visible; ambiguity is still rejected.
          const all = page.locator(step.selector);
          await all.first().waitFor({ state: 'hidden', timeout: 5000 });
          const count = await all.count();
          if (count > 1) throw new Error(`clearambiguityerror: expected at most 1, found ${count} for ${step.selector}`);
          evidence.push({ action: 'expect_hidden', selector: step.selector, count });
          hiddenSoFar.push(step.selector);
          continue;
        }
        if (step.action === 'expect_animated') {
          // Observe the element right after the triggering click: a real transition passes through
          // intermediate heights or opacities; an instant change does not.
          const samples = [];
          const started = Date.now();
          while (Date.now() - started < 700) {
            const probe = page.locator(step.selector).first();
            samples.push(await probe.count() ? await probe.evaluate(el => {
              const r = el.getBoundingClientRect();
              return { h: Math.round(r.height * 10) / 10, o: Math.round(parseFloat(getComputedStyle(el).opacity) * 100) / 100 };
            }, null, { timeout: 100 }).catch(() => null) : null);
            await page.waitForTimeout(30);
          }
          // Opacity only counts while the element actually occupies space; fading an element that already
          // collapsed to zero height looks like an instant change.
          if (preAnimation) samples.unshift(preAnimation);
          preAnimation = null;
          const series = key => samples.filter(Boolean).filter(x => key === 'h' || x.h > 1).map(x => x[key]);
          // Gradual means intermediate values in BOTH halves of the range (an instant jump followed by a
          // small tail does not count). A large height change must itself be gradual; opacity alone only
          // counts for changes that keep their size (pure fades).
          const spread = values => {
            if (values.length < 3) return false;
            const lo = Math.min(...values), hi = Math.max(...values), mid = (lo + hi) / 2;
            const inner = values.filter(v => v > lo && v < hi);
            return new Set(inner).size >= 2 && inner.some(v => v >= mid) && inner.some(v => v <= mid);
          };
          const heights = series('h');
          const heightRange = heights.length ? Math.max(...heights) - Math.min(...heights) : 0;
          const steps = heightRange > 50 ? (spread(heights) ? 2 : 0) : ((spread(heights) || spread(series('o'))) ? 2 : 0);
          if (steps < 2) throw new Error(`no gradual animation on ${step.selector}: heights ${JSON.stringify(heights.slice(0, 14))}, opacities ${JSON.stringify(series('o').slice(0, 14))}; the change must pass through intermediate values across the whole range (a jump followed by a short tail, or fading an element whose height already snapped, does not count)`);
          evidence.push({ action: 'expect_animated', selector: step.selector, intermediate: steps });
          continue;
        }
        if (step.action === 'remember_style' || step.action === 'expect_same_style') {
          const target = await resolveLocator(step.selector);
          const look = await target.evaluate(el => {
            const c = getComputedStyle(el), r = el.getBoundingClientRect();
            const pick = ['background-color', 'color', 'border-top-width', 'border-top-style', 'border-top-color', 'border-top-left-radius',
              'font-size', 'font-weight', 'font-family', 'padding-top', 'padding-left', 'box-shadow'];
            return Object.assign(Object.fromEntries(pick.map(k => [k, c.getPropertyValue(k)])), { height: Math.round(r.height) + 'px' });
          });
          if (step.action === 'remember_style') {
            remembered[step.value] = look;
            evidence.push({ action: 'remember_style', selector: step.selector, look });
            continue;
          }
          const base = remembered[step.value];
          if (!base) throw new Error(`no remembered style named ${step.value}`);
          const differs = Object.keys(base).filter(k => {
            const a = base[k], b = look[k];
            const na = parseFloat(a), nb = parseFloat(b);
            if (/px$/.test(a) && /px$/.test(b) && !isNaN(na) && !isNaN(nb)) return Math.abs(na - nb) > 1;
            return a !== b;
          }).map(k => `${k}: expected ${base[k]} got ${look[k]}`);
          if (differs.length) throw new Error(`style of ${step.selector} differs from ${step.value}: ${differs.join('; ')}`);
          evidence.push({ action: 'expect_same_style', selector: step.selector, compared: Object.keys(base).length });
          continue;
        }
        if (step.action === 'expect_text' || step.action === 'expect_visible') {
          // Several matches (e.g. a summary and a field message): the expectation holds if any matching
          // visible element satisfies it. Actions (click/fill/select) still require exactly one target.
          const all = page.locator(step.selector);
          const deadline = Date.now() + 5000;
          let observed = [];
          while (Date.now() < deadline) {
            observed = [];
            const n = await all.count();
            for (let i = 0; i < n; i++) {
              const item = all.nth(i);
              if (!(await item.evaluate((el, fn) => (new Function('return ' + fn)())(el), reallyVisible.toString()).catch(() => false))) continue;
              observed.push(step.action === 'expect_text' ? (await item.innerText()) : 'visible');
            }
            if (step.action === 'expect_visible' ? observed.length > 0 : observed.some(t => t.includes(step.value))) break;
            await page.waitForTimeout(100);
          }
          const ok = step.action === 'expect_visible' ? observed.length > 0 : observed.some(t => t.includes(step.value));
          if (!ok) throw new Error(`${step.action} on ${step.selector}: none of ${await all.count()} matches satisfied it; visible texts: ${JSON.stringify(observed).slice(0, 300)}`);
          evidence.push({ action: step.action, selector: step.selector, matches: observed.length });
          continue;
        }
        const loc = await resolveLocator(step.selector);
        if (step.action === 'click') {
          await loc.click({ timeout: 5000 });
          evidence.push({ action: 'click', selector: step.selector });
        } else if (step.action === 'fill') {
          await loc.fill(step.value, { timeout: 5000 });
          evidence.push({ action: 'fill', selector: step.selector, value: step.value });
        } else if (step.action === 'expect_visible') {
          await loc.waitFor({ state: 'visible', timeout: 5000 });
          evidence.push({ action: 'expect_visible', selector: step.selector });
        } else if (step.action === 'select') {
          await loc.selectOption(step.value, {timeout: 5000});
          evidence.push({ action: 'select', selector: step.selector, value: step.value });
        } else if (step.action === 'expect_text') {
          const val = await retryMatch(async () => (await loc.innerText()), step.value);
          evidence.push({ action: 'expect_text', selector: step.selector, observed: val });
        } else if (step.action === 'expect_value') {
          const val = await retryMatch(async () => (await loc.inputValue()), step.value);
          if (val !== step.value) throw new Error(`Value mismatch: expected ${step.value}, observed ${val}`);
          evidence.push({ action: 'expect_value', selector: step.selector, observed: val });
        } else {
          throw new Error(`Unknown action: ${step.action}`);
        }
       } catch (err) {
        if (step.action === 'expect_hidden') throw err;
        const why = await diagnose(step);
        throw new Error(`step ${evidence.length + 1} (${step.action} ${step.selector}) failed: ${String(err.message).split('\n')[0]}` + (why ? ` | DIAGNOSTIC: ${why}` : ''));
       }
      }
      return { status: 'passed', reason: '', evidence };
    }

    throw new Error(`Unknown op: ${check.op}`);
  } catch (e) {
    return { status: 'failed', reason: e.message, evidence: {} };
  }
}

module.exports = { inspect, run };
