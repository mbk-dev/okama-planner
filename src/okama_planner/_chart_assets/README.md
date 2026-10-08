# Offline chart assets

`echarts.min.js` is the unmodified Apache ECharts **6.1.0** browser distribution,
identical to the version used by okama-web Portfolio at implementation time.

- Upstream: https://github.com/apache/echarts/releases/tag/6.1.0
- npm package: https://www.npmjs.com/package/echarts/v/6.1.0
- SHA256 (`echarts.min.js`): `b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0`
- Redistributed license: `ECHARTS-LICENSE.txt`, including bundled third-party terms.
- Notices: `ECHARTS-NOTICE.txt` and `LICENSE-d3.txt`.

`charts.js` and `page.html` are Planner's own MIT-licensed rendering adapter and
responsive page. The adapter follows the fan-chart visual settings in okama-web's
`src/charts/fanOption.ts`, `baseOption.ts`, `theme.ts` and `export/chartImage.ts`:
median width/color, band gradients, endpoint labels, calendar density and right axis.
It retains negative capital with `stackStrategy: 'all'` and labels the opening point
`Forecast start`, as a saved plan need not start today. No original web code is bundled.

Keep this distribution pinned and the checksum/notices updated when upgrading.
The Python exporter embeds these assets into HTML; consumers need no npm packages
or CDN connection. PNG/SVG use the same adapter and engine in headless Chrome.
