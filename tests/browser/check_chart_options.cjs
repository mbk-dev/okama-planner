/* Fast checks of the real chart options and custom logarithmic band geometry. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/okama_planner/_chart_assets/charts.js'), 'utf8');
const rows = [
  { month: '2028-01', p10: -10, p25: 0, p50: 10, p75: 100, p90: 1000 },
  { month: '2028-02', p10: 1, p25: 10, p50: 100, p75: 1000, p90: 10000 },
  { month: '2028-03', p10: 10, p25: 100, p50: 1000, p75: 10000, p90: 100000 }
];
function run(capital = rows, portfolio = rows) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { clientWidth: 1000, style: {}, hidden: true,
      children: [], appendChild(child) { this.children.push(child); },
      addEventListener(event, fn) { this[event] = fn; } });
    return elements.get(id);
  };
  const input = { currency: 'USD', charts: { portfolio, capital }, goals: [
    { number: 1, month: '2028-02', label: '<img src=x>' },
    { number: 2, month: '2028-02', label: 'Retirement' }
  ] };
  get('forecast-data').textContent = JSON.stringify(input);
  const charts = new Map();
  const document = { getElementById: get,
    createElement: () => ({ style: {} }),
    querySelectorAll: selector => selector === '[data-scale]' ? ['portfolio', 'capital'].map(key => {
      const element = get(key + '-toggle'); element.dataset = { scale: key }; return element;
    }) : [] };
  const echarts = { init(host) { const chart = { setOption(option) { this.option = option; }, resize() {} };
    charts.set(host, chart); return chart; }, graphic: { clipPointsByRect: points => points } };
  vm.runInNewContext(source, { document, echarts, ResizeObserver: class { observe() {} } });
  return { get, charts };
}
const { get, charts } = run();
const portfolio = charts.get(get('portfolio'));
assert.deepEqual(Array.from(portfolio.option.series.find(s => s.name === 'Median').markLine.data, g => g.label.formatter), ['1', '2']);
assert.equal(get('portfolio-goals').children[0].textContent, '1 — <img src=x> (2028-02)');
const linear = JSON.stringify(portfolio.option.series.map(s => s.data));
get('portfolio-toggle').checked = true;
get('portfolio-toggle').change();
assert.equal(portfolio.option.yAxis.type, 'log');
assert.equal(charts.get(get('capital')).option.yAxis.type, 'value');
assert.equal(get('portfolio-scale-note').hidden, false);
const lower = portfolio.option.series.find(s => s.name === 'p10');
assert.deepEqual(Array.from(lower.data), [null, 1, 10], 'Log axis extent must include every positive lower bound');
const median = portfolio.option.series.find(s => s.name === 'Median');
assert.deepEqual(Array.from(median.data), [10, 100, 1000]);
const band = portfolio.option.series.find(s => s.name === 'outer-band');
assert.deepEqual(JSON.parse(JSON.stringify(band.data)), [[1, 1, 10000, 10, 100000]],
  'Cross-zero band interval must be a gap with explicit remaining segment and bounds');
const polygon = band.renderItem({ dataIndex: 0 }, { value: () => 1,
  coord: ([x, y]) => [x * 100, 600 - 100 * Math.log10(y)], style: () => ({}) });
assert.deepEqual(JSON.parse(JSON.stringify(polygon.shape.points)), [[100, 600], [100, 200], [200, 100], [200, 500]]);
get('portfolio-toggle').checked = false;
get('portfolio-toggle').change();
assert.equal(JSON.stringify(portfolio.option.series.map(s => s.data)), linear);
const negative = rows.map(row => ({ ...row, p10: -50, p25: -40, p50: -30, p75: -20, p90: 0 }));
const depleted = run(negative);
assert.equal(depleted.get('capital-toggle').disabled, true);
assert.match(depleted.get('capital-scale-note').textContent, /no positive/i);
console.log('Chart option checks passed: independent scales, band geometry, gaps, goals, safe labels, depletion');

// Use the bundled real engine: custom-series indexes must never become money values,
// and skipping an interval must not shift the category coordinate to an earlier row.
const echarts = require('../../src/okama_planner/_chart_assets/echarts.min.js');
const highRows = rows.map(row => ({ ...row, p10: 1000, p25: 2000, p50: 3000, p75: 4000, p90: 5000 }));
for (const fixture of [highRows, rows]) {
  const fixtureRun = run(fixture, fixture);
  fixtureRun.get('portfolio-toggle').checked = true;
  fixtureRun.get('portfolio-toggle').change();
  const option = fixtureRun.charts.get(fixtureRun.get('portfolio')).option;
  const actual = echarts.init(null, undefined, { renderer: 'svg', ssr: true, width: 1000, height: 600 });
  try {
    actual.setOption(option);
    const extent = actual.getModel().getComponent('yAxis').axis.scale.getExtent();
    const minimum = Math.min(...fixture.flatMap(row => ['p10', 'p25', 'p50', 'p75', 'p90']
      .map(p => row[p]).filter(value => value > 0)));
    assert(extent[0] >= 10 ** Math.floor(Math.log10(minimum)),
      `Custom segment indexes contaminated log axis extent: ${extent}, minimum ${minimum}`);
    for (const name of ['outer-band', 'inner-band']) {
      const seriesData = actual.getModel().getSeriesByName(name)[0].getData();
      for (const dimension of seriesData.mapDimensionsAll('y')) {
        assert(seriesData.getApproximateExtent(dimension)[0] >= minimum,
          'Custom band monetary dimensions must exclude segment indexes');
      }
    }
    const svg = actual.renderToSVGString();
    assert(!svg.includes('NaN'), 'Skipped log intervals must not produce invalid polygon coordinates');
    const model = actual.getModel().getSeriesByName('outer-band')[0];
    const points = model.getData().getItemGraphicEl(0).shape.points;
    const index = fixture === rows ? 1 : 0;
    const expected = [[index, fixture[index].p10], [index, fixture[index].p90],
      [index + 1, fixture[index + 1].p90], [index + 1, fixture[index + 1].p10]]
      .map(point => actual.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point));
    points.forEach((point, i) => point.forEach((coordinate, j) =>
      assert(Math.abs(coordinate - expected[i][j]) < 0.01, 'Real log polygon must use correct saved interval')));
  } finally { actual.dispose(); }
}
console.log('Real ECharts regression checks passed: monetary axis extent and skipped-interval coordinates');
