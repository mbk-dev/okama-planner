const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('path');

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 800 }, deviceScaleFactor: 2,
    });
    await page.goto('file://' + path.resolve('tmp/readme-charts/forecast.html'));
    await page.waitForFunction(() =>
      !!echarts.getInstanceByDom(document.getElementById('portfolio')));
    await page.locator('[data-scale="portfolio"]').check();
    await page.evaluate(() => {
      document.getElementById('portfolio').style.height = '420px';
    });
    // Let the exporter's ResizeObserver finish before applying presentation bounds.
    await page.waitForTimeout(300);
    const metadata = await page.evaluate(() => {
      const chart = echarts.getInstanceByDom(document.getElementById('portfolio'));
      chart.setOption({ yAxis: { min: 100, max: 1000000 } });
      return {
        scale: chart.getOption().yAxis[0].type,
        goals: document.querySelectorAll('#portfolio-goals li').length,
      };
    });
    if (metadata.scale !== 'log' || metadata.goals !== 3) {
      throw new Error(JSON.stringify(metadata));
    }
    const download = page.waitForEvent('download');
    await page.locator('button[data-chart="portfolio"][data-format="png"]').click();
    await (await download).saveAs('docs/images/financial-plan-three-goals.png');
    console.log(metadata);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
