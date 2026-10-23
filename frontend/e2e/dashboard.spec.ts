import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const screenshotRoot = path.resolve('../docs/screenshots');
const benchmarkRoot = path.resolve('../artifacts/phase6');
const pages = [
  ['overview', 'Overview'],
  ['data-quality', 'Data quality'],
  ['forecasts', 'Forecast explorer'],
  ['inventory', 'Inventory planner'],
  ['scenarios', 'Scenario comparison'],
  ['performance', 'Model performance'],
] as const;

async function ready(page: Page) {
  await expect(page.locator('main h1')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('main').getByRole('status')).toHaveCount(0);
}

async function capture(page: Page, name: string) {
  await mkdir(screenshotRoot, { recursive: true });
  await page.screenshot({ path: path.join(screenshotRoot, name), fullPage: true });
  if (name === 'overview-desktop.png') {
    await page.screenshot({ path: path.join(screenshotRoot, 'overview-viewport.png') });
  }
}

test('real dataset activation → frozen run → forecast → inventory → comparison → CSV', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const started = performance.now();
  await page.goto('/#/data-quality');
  await page.getByRole('button', { name: 'Activate data', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Activate historical sample', exact: true }).click();
  await expect(dialog.getByText('Workspace updated', { exact: true })).toBeVisible({
    timeout: 120_000,
  });
  await dialog.getByRole('button', { name: 'Close workspace setup' }).click();
  await ready(page);
  const products = page.getByRole('table', { name: 'Products selected from training history' });
  await expect(products.getByRole('row')).toHaveCount(51);
  await page.getByLabel('Filter selected products').fill('84077');
  await expect(products.getByRole('row')).toHaveCount(2);
  await expect(products.getByRole('row').nth(1)).toContainText('84077');
  await page.getByLabel('Filter selected products').fill('');
  await page.getByRole('link', { name: 'Forecast explorer', exact: true }).click();
  await ready(page);
  await page.getByRole('combobox', { name: 'Product', exact: true }).selectOption('84077');
  await ready(page);
  await expect(page.locator('main')).toContainText('84077');
  const forecastDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click();
  const forecastFile = await forecastDownload;
  const forecastPath = await forecastFile.path();
  expect(forecastPath).not.toBeNull();
  const forecasts = await readFile(forecastPath!, 'utf8');
  expect(forecasts).toContain('forecast_id,stock_code,week,method,point');
  expect(forecasts.trim().split('\n')).toHaveLength(2401);
  await page.getByRole('link', { name: 'Inventory planner', exact: true }).click();
  await ready(page);
  // The rest of the workflow changes real planner inputs and submits a durable simulation.
  const selectedPreview = page.waitForResponse(
    (response) =>
      response.url().endsWith('/inventory/preview') &&
      response.request().postDataJSON()?.stock_code === '84077' &&
      response.ok(),
  );
  await page.getByRole('combobox', { name: 'Planner product', exact: true }).selectOption('84077');
  await selectedPreview;
  await expect(page.locator('.planner-results')).toHaveAttribute('aria-busy', 'false');
  const changedPreview = page.waitForResponse((response) => {
    if (!response.url().endsWith('/inventory/preview') || !response.ok()) return false;
    const body = response.request().postDataJSON();
    return (
      body?.stock_code === '84077' &&
      body.on_hand === 120 &&
      body.parameters?.lead_time_weeks === 2 &&
      body.parameters?.case_pack_size === 6 &&
      body.parameters?.min_order_quantity === 12
    );
  });
  await page.getByLabel('On-hand inventory', { exact: true }).fill('120');
  await page.getByLabel('Lead time (weeks)', { exact: true }).fill('2');
  await page.getByLabel('Case-pack size', { exact: true }).fill('6');
  await page.getByLabel('Minimum order quantity', { exact: true }).fill('12');
  const changed = await (await changedPreview).json();
  await expect(page.locator('.recommendation-hero strong')).toContainText(
    new Intl.NumberFormat('en-GB').format(changed.recommendation.recommended_order_quantity),
  );
  await expect(
    page.getByRole('button', { name: 'Export recommendation', exact: true }),
  ).toBeVisible();
  await expect(page.locator('.planner-results')).toHaveAttribute('aria-busy', 'false');
  const previewResponse = await request.post('/api/inventory/preview', {
    data: {
      forecast_id: (await (await request.get('/api/dashboard/context')).json()).one_week_forecast
        .forecast_id,
      stock_code: '84077',
      on_hand: 120,
      parameters: { lead_time_weeks: 2, case_pack_size: 6, min_order_quantity: 12 },
    },
  });
  expect(previewResponse.ok()).toBeTruthy();
  const preview = await previewResponse.json();
  expect(preview.recommendation.recommended_order_quantity % 6).toBe(0);
  expect(preview.error_estimate.test_residuals_used).toBe(false);
  await page.getByRole('button', { name: 'Run inventory simulation', exact: true }).click();
  await expect(page).toHaveURL(/#\/scenarios$/, { timeout: 120_000 });
  await page.getByRole('link', { name: 'Scenario comparison', exact: true }).click();
  await ready(page);
  await expect(page.locator('main')).toContainText('ML + safety stock');
  await expect(page.locator('main')).toContainText('Mean + safety stock');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Recommendations CSV', exact: true }).click();
  const exported = await download;
  const exportedPath = await exported.path();
  expect(exportedPath).not.toBeNull();
  const csv = await readFile(exportedPath!, 'utf8');
  expect(csv).toContain('recommended_order_quantity');
  expect(csv.trim().split('\n')).toHaveLength(2001);
  const duration = performance.now() - started;
  await mkdir(benchmarkRoot, { recursive: true });
  await writeFile(
    path.join(benchmarkRoot, 'browser-workflow.json'),
    JSON.stringify(
      {
        scope:
          'real browser UI, real HTTP API, durable worker and PostgreSQL; historical sample; no final reevaluation',
        browser: 'Chromium',
        workflow_ms: duration,
        forecast_export_rows: 2400,
        recommendation_export_rows: 2000,
        scenario_assumptions: {
          scope: 'Parameters apply to all 50 products; stock override applies to 84077',
          stock_code: '84077',
          initial_on_hand: 120,
          lead_time_weeks: 2,
          case_pack_size: 6,
          min_order_quantity: 12,
        },
      },
      null,
      2,
    ),
  );
  expect(errors).toEqual([]);
});

test('all six pages render real data, pass automated accessibility checks and fit mobile', async ({
  page,
}) => {
  const samples: { page: string; load_ms: number }[] = [];
  const accessibility: { page: string; viewport: string; violations: number }[] = [];
  for (const [route, label] of pages) {
    const start = performance.now();
    await page.goto(`/#/${route}`);
    await ready(page);
    samples.push({ page: label, load_ms: performance.now() - start });
    const violations = (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
    ).violations;
    expect(violations).toEqual([]);
    accessibility.push({ page: label, viewport: '1440x1000', violations: violations.length });
    await capture(page, `${route}-desktop.png`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [route, label] of pages) {
    await page.goto(`/#/${route}`);
    await ready(page);
    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(
      dimensions.documentWidth,
      `${route}: document should fit the mobile viewport`,
    ).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
    const violations = (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
    ).violations;
    expect(violations).toEqual([]);
    accessibility.push({ page: label, viewport: '390x844', violations: violations.length });
  }
  await page.goto('/#/inventory');
  await ready(page);
  await capture(page, 'inventory-mobile.png');
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await page.getByRole('link', { name: 'Data quality', exact: true }).click();
  await expect(page).toHaveURL(/#\/data-quality$/);
  // A new document starts keyboard navigation at the first focusable control;
  // hash navigation intentionally retains the previously clicked link's focus.
  const keyboardPage = await page.context().newPage();
  await keyboardPage.goto('/#/overview');
  await ready(keyboardPage);
  await keyboardPage.keyboard.press('Tab');
  await expect(keyboardPage.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  await keyboardPage.keyboard.press('Enter');
  await expect(keyboardPage.locator('main')).toBeFocused();
  await keyboardPage.close();
  await mkdir(benchmarkRoot, { recursive: true });
  await writeFile(
    path.join(benchmarkRoot, 'accessibility-checks.json'),
    JSON.stringify(
      {
        scope: 'Automated axe checks; not complete accessibility certification',
        checks: accessibility,
      },
      null,
      2,
    ),
  );
  await writeFile(
    path.join(benchmarkRoot, 'browser-page-loads.json'),
    JSON.stringify(
      {
        scope:
          'single local warm navigation sample per page including verified data reads; not a load benchmark',
        samples,
      },
      null,
      2,
    ),
  );
});

test('proxy serves live OpenAPI and the UI handles dependency failure safely', async ({
  page,
  request,
}) => {
  const schema = await request.get('/api/openapi.json');
  expect(schema.ok()).toBeTruthy();
  expect((await schema.json()).paths).toHaveProperty('/inventory/preview');
  const docs = await request.get('/api/docs');
  expect(await docs.text()).toContain('/api/openapi.json');
  await page.route('**/api/dashboard/context*', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'database_unavailable', message: 'Private detail must not render' },
      }),
    }),
  );
  await page.goto('/#/overview');
  await expect(page.getByRole('alert')).toContainText('The database is unavailable');
  await expect(page.locator('body')).not.toContainText('Private detail');
  await page.unroute('**/api/dashboard/context*');
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await ready(page);
});
