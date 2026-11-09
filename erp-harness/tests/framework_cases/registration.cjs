const { expect } = require('assert');

module.exports = async function check(ctx) {
  const { page, assert } = ctx;
  const isolatedPage = await page.context().newPage();
  isolatedPage.setDefaultTimeout(5000);
  const pageErrors = [];
  const unexpectedWrites = [];
  const mockedItems = [];
  let capturedPost = null;

  isolatedPage.on('pageerror', (err) => pageErrors.push(err.message));

  await isolatedPage.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();

    if (url.pathname === '/api/inventory' && (method === 'GET' || method === 'HEAD' || method === 'OPTIONS')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockedItems) });
    }

    if (url.pathname === '/api/inventory' && method === 'POST') {
      try {
        const postDataJSON = JSON.parse(req.postData() || '{}');
        capturedPost = postDataJSON;
        const newRecord = { ...postDataJSON, id: 999901, createdAt: '2026-01-01T00:00:00Z' };
        mockedItems.push(newRecord);
        return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newRecord) });
      } catch (e) {
        return route.fulfill({ status: 400 });
      }
    }

    if (!['GET','HEAD','OPTIONS'].includes(method)) {
      unexpectedWrites.push(`${method} ${url.pathname}`);
      return route.abort();
    }
    return route.continue();
  });

  try {
    await isolatedPage.goto(page.url(), { waitUntil: 'networkidle' });
    const expandBtn = isolatedPage.getByRole('button', { name: /Expand sidebar|펼치기/i });
    if (await expandBtn.isVisible()) {
      await expandBtn.click();
    }
    await isolatedPage.getByRole('navigation', { name: 'Side navigation', exact: true }).getByRole('button', { name: '재고', exact: true }).click();

    const sidePanel = isolatedPage.getByTestId('side-panel');
    const sideForms=sidePanel.locator('form:visible');
    const { inventoryLocators, formAction } = require(require('node:path').resolve(ctx.root, '../platform/tests/inventory_locators.cjs'));
    const forms=(await sideForms.count())>0 ? sideForms : inventoryLocators(isolatedPage).form;
    const targetForm=forms;
    assert.strictEqual(await targetForm.count(), 1, 'Exactly one valid form must exist');
    const form=targetForm;

    const resetBtn = (await sidePanel.isVisible()) ? sidePanel.getByRole('button', { name: /신규|신규 등록/ }) : null;
    if (resetBtn && (await resetBtn.count()) === 1 && await resetBtn.isVisible()) await resetBtn.click();

    const name = 'harness_create_' + Date.now();
    const category = '검사용 분류';
    const data = { name, category, quantity: 7, minQuantity: 2, unitPrice: 1234 };

    const nameInput = form.getByLabel(/^이름/);
    await nameInput.fill(name);
    assert.strictEqual(await nameInput.inputValue(), name);

    const catInput = form.getByLabel(/^(카테고리|분류)/);
    if (await catInput.evaluate(el => el.tagName === 'SELECT')) {
      const val = await catInput.locator('option').evaluateAll(options => options.filter(o => o.value && o.disabled === false).map(o => o.value));
      const firstVal = val[0];
      assert.ok(val.length > 0, 'No valid options');
      await catInput.selectOption(firstVal);
      data.category = await catInput.inputValue();
    } else {
      await catInput.fill(category);
      data.category = category;
    }
    assert.strictEqual(await catInput.inputValue(), data.category);

    const qtyInput = form.getByLabel(/^수량/);
    await qtyInput.fill('7');
    assert.strictEqual(await qtyInput.inputValue(), '7');

    const minQtyInput = form.getByLabel(/^최소\s*수량/);
    await minQtyInput.fill('2');
    assert.strictEqual(await minQtyInput.inputValue(), '2');

    const priceInput = form.getByLabel(/^단가/);
    await priceInput.fill('1234');
    assert.strictEqual(await priceInput.inputValue(), '1234');

    const submitBtn = await formAction(isolatedPage, form, /추가|등록|저장/);
    assert.strictEqual(await submitBtn.count(), 1);

    const requestPromise = isolatedPage.waitForRequest(r => 
      new URL(r.url()).pathname === '/api/inventory' && r.method() === 'POST', 
      { timeout: 5000 }
    ).catch(() => null);

    await submitBtn.click();
    const request = await requestPromise;

    assert.ok(request, '등록 버튼이 POST /api/inventory를 보내지 않았습니다.');
    const sentJson = JSON.parse(request.postData());
    assert.strictEqual(sentJson.name, name);
    assert.strictEqual(sentJson.category, data.category);
    assert.strictEqual(Number(sentJson.quantity), 7);
    assert.strictEqual(Number(sentJson.minQuantity), 2);
    assert.strictEqual(Number(sentJson.unitPrice), 1234);

    await isolatedPage.getByRole('cell', { name, exact: true }).waitFor();
    assert.strictEqual(pageErrors.length, 0, `Page errors: ${pageErrors.join(', ')}`);
    assert.strictEqual(unexpectedWrites.length, 0, `Unexpected writes: ${unexpectedWrites.join(', ')}`);
    
    console.log('REGISTRATION_FLOW_OK');
  } finally {
    await isolatedPage.close();
  }
};
