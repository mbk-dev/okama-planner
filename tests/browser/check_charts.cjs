/* Optional browser acceptance: run with Playwright installed in the development environment. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const html = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome' });
  try {
    const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    const network = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
    await context.setOffline(true);
    await page.goto(pathToFileURL(html).href);
    await page.waitForFunction(() => !!echarts.getInstanceByDom(document.getElementById('portfolio')));
    const sizes = () => page.evaluate(() => Object.fromEntries(['portfolio', 'capital'].map(key => {
      const chart = echarts.getInstanceByDom(document.getElementById(key));
      return [key, { width: chart.getWidth(), height: chart.getHeight() }];
    })));
    const desktop = await sizes();
    assert(desktop.portfolio.width > 1000);
    const bandErrors = await page.evaluate(() => {
      const data = JSON.parse(document.getElementById('forecast-data').textContent);
      const mismatches = [];
      for (const key of ['portfolio', 'capital']) {
        const chart = echarts.getInstanceByDom(document.getElementById(key));
        for (const p of ['p75', 'p90']) {
          const series = chart.getModel().getSeriesByName(p)[0].getData();
          const stackedDimension = series.getCalculationInfo('stackResultDimension');
          data.charts[key].forEach((row, index) => {
            if (Math.abs(series.get(stackedDimension, index) - row[p]) > 1e-7)
              mismatches.push({ key, percentile: p, index });
          });
        }
      }
      return mismatches;
    });
    assert.deepEqual(bandErrors, [], 'Fan bands must end at the saved upper percentile, including below zero');
    const goalChecks = await page.evaluate(() => {
      const input = JSON.parse(document.getElementById('forecast-data').textContent);
      return ['portfolio', 'capital'].map(key => {
        const chart = echarts.getInstanceByDom(document.getElementById(key));
        const marks = chart.getOption().series.find(series => series.name === 'Median').markLine.data;
        return { marks: marks.map(mark => ({ month: mark.xAxis, number: mark.label.formatter })),
          expected: input.goals.map(goal => ({ month: goal.month, number: String(goal.number) })),
          annotations: document.getElementById(key + '-goals').children.length };
      });
    });
    for (const check of goalChecks) {
      assert.deepEqual(check.marks, check.expected);
      assert.equal(check.annotations, check.expected.length);
    }
    assert.equal(await page.locator('#license-notices').isVisible(), false);
    await page.locator('[data-scale="portfolio"]').check();
    const logErrors = await page.evaluate(() => {
      const input = JSON.parse(document.getElementById('forecast-data').textContent);
      const chart = echarts.getInstanceByDom(document.getElementById('portfolio'));
      const failures = [];
      if (chart.getOption().yAxis[0].type !== 'log') failures.push('Portfolio log axis missing');
      if (echarts.getInstanceByDom(document.getElementById('capital')).getOption().yAxis[0].type !== 'value')
        failures.push('Capital scale changed with portfolio');
      for (const [name, low, high] of [['outer-band', 'p10', 'p90'], ['inner-band', 'p25', 'p75']]) {
        const model = chart.getModel().getSeriesByName(name)[0];
        const indices = chart.getOption().series.find(series => series.name === name).data.map(item => item[0]);
        const expectedIndices = input.charts.portfolio.slice(0, -1).flatMap((row, index) =>
          row[low] > 0 && input.charts.portfolio[index + 1][low] > 0 ? [index] : []);
        if (JSON.stringify(indices) !== JSON.stringify(expectedIndices)) failures.push(name + ' missing gaps');
        indices.forEach((index, itemIndex) => {
          const rows = input.charts.portfolio;
          const expected = [[index, rows[index][low]], [index, rows[index][high]],
            [index + 1, rows[index + 1][high]], [index + 1, rows[index + 1][low]]]
            .map(point => chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point));
          const points = model.getData().getItemGraphicEl(itemIndex)?.shape.points;
          if (!points || points.some((point, i) => point.some((coordinate, j) =>
            !Number.isFinite(coordinate) || Math.abs(coordinate - expected[i][j]) > 0.01)))
            failures.push(name + ' polygon differs from saved bounds at ' + index);
        });
      }
      return failures;
    });
    assert.deepEqual(logErrors, [], 'Log band geometry must project actual saved endpoints');
    await page.screenshot({ path: path.join(output, 'log-desktop.png'), fullPage: true });
    for (const format of ['png', 'svg']) {
      const pending = page.waitForEvent('download');
      await page.locator(`button[data-chart="portfolio"][data-format="${format}"]`).click();
      const download = await pending;
      const target = path.join(output, `portfolio-log.${format}`);
      await download.saveAs(target);
      assert(fs.statSync(target).size > 1000);
      if (format === 'svg') {
        const svg = fs.readFileSync(target, 'utf8');
        assert(svg.includes('linearGradient'), 'SVG export lost log fan fills');
        assert(!svg.includes('Forecast start'));
        assert(!svg.includes('NaN'));
      }
    }
    await page.locator('[data-scale="portfolio"]').uncheck();
    for (const viewport of [{ width: 320, height: 240 }, { width: 390, height: 900 },
      { width: 900, height: 390 }, { width: 2048, height: 916 },
      { width: 1280, height: 900 }, { width: 900, height: 1200 }]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(100);
      const overlaps = await page.evaluate(() => [...document.querySelectorAll('.card')].some(card => {
        const chart = card.querySelector('.chart').getBoundingClientRect();
        const controls = card.querySelector('.controls').getBoundingClientRect();
        return controls.top < chart.bottom || card.scrollWidth > card.clientWidth ||
          [...card.querySelectorAll('button, .scale-toggle')].some(element => {
            const rect = element.getBoundingClientRect();
            return rect.top < chart.bottom || rect.right > card.getBoundingClientRect().right;
          });
      }));
      assert.equal(overlaps, false, 'Controls overlap or overflow at ' + JSON.stringify(viewport));
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(100);
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    for (const key of ['portfolio', 'capital']) {
      for (const format of ['png', 'svg']) {
        const pending = page.waitForEvent('download');
        await page.locator(`button[data-chart="${key}"][data-format="${format}"]`).click();
        const download = await pending;
        assert.equal(download.suggestedFilename(), `${key}.${format}`);
        const target = path.join(output, `${key}.${format}`);
        await download.saveAs(target);
        const content = fs.readFileSync(target);
        if (format === 'png') {
          assert.equal(content.readUInt32BE(16), desktop[key].width * 2);
          assert.equal(content.readUInt32BE(20), desktop[key].height * 2);
        } else {
          assert(content.toString().includes(`viewBox="0 0 ${desktop[key].width} ${desktop[key].height}"`));
          assert(content.toString().includes('p90'));
        }
      }
    }
    await page.setViewportSize({ width: 390, height: 650 });
    await page.waitForFunction(() => echarts.getInstanceByDom(document.getElementById('portfolio')).getWidth() < 400);
    const mobile = await sizes();
    assert(mobile.portfolio.width < desktop.portfolio.width);
    assert(mobile.portfolio.height < desktop.portfolio.height);
    assert(mobile.capital.width < 400);
    assert.equal(await page.locator('input[type=number], select').count(), 0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow, false);
    const firstYearLabel = await page.evaluate(() => {
      const chart = echarts.getInstanceByDom(document.getElementById('portfolio'));
      const firstYear = JSON.parse(document.getElementById('forecast-data').textContent)
        .charts.portfolio[0].month.slice(0, 4);
      return chart.getZr().storage.getDisplayList().filter(element =>
        element.type === 'tspan' && element.style.text === firstYear).map(element => {
          const bounds = element.getBoundingRect().clone();
          bounds.applyTransform(element.getComputedTransform());
          return bounds.x;
        });
    });
    assert(firstYearLabel.length > 0);
    assert(firstYearLabel.every(x => x >= 0), 'First calendar label is clipped on a narrow screen');
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
    const pending = page.waitForEvent('download');
    await page.locator('button[data-chart="portfolio"][data-format="png"]').click();
    const download = await pending;
    const resizedPath = path.join(output, 'portfolio-mobile.png');
    await download.saveAs(resizedPath);
    const resized = fs.readFileSync(resizedPath);
    assert.equal(resized.readUInt32BE(16), mobile.portfolio.width * 2);
    assert.equal(resized.readUInt32BE(20), mobile.portfolio.height * 2);
    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForFunction(() => echarts.getInstanceByDom(document.getElementById('portfolio')).getHeight() > 423);
    const taller = await sizes();
    assert.equal(taller.portfolio.width, mobile.portfolio.width);
    assert(taller.portfolio.height > mobile.portfolio.height);
    assert.deepEqual(network, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ desktop, mobile, taller, browserDownloads: 7, externalRequests: network.length, errors }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
