/* ECharts fan styling follows okama-web Portfolio: blue median and nested bands. */
(() => {
  'use strict';
  const input = JSON.parse(document.getElementById('forecast-data').textContent);
  const t = text => input.labels?.[text] || text;
  const font = 'system-ui,-apple-system,Segoe UI,Roboto,sans-serif';
  const blue = '#2a78d6';
  const muted = '#898781';
  const charts = new Map();
  const scales = new Map();
  const moneyFormat = new Intl.NumberFormat(input.locale || 'en-US', {
    style: 'currency', currency: input.currency, currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 0, maximumFractionDigits: 0
  });
  const money = value => moneyFormat.format(value);
  const numberFormat = new Intl.NumberFormat(input.locale || 'en-US', { maximumFractionDigits: 2 });
  const monthFormat = new Intl.DateTimeFormat(input.locale || 'en-US', {
    year: 'numeric', month: 'short', timeZone: 'UTC'
  });
  const monthLabel = month => monthFormat.format(new Date(month + '-01T00:00:00Z'));
  const gradient = opacity => ({
    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [{ offset: 0, color: `rgba(42,120,214,${opacity})` },
                 { offset: 1, color: `rgba(42,120,214,${opacity * 0.6})` }]
  });

  function option(key, width) {
    const rows = input.charts[key];
    const logarithmic = scales.get(key) === true;
    const value = (row, percentile) => logarithmic && row[percentile] <= 0 ? null : row[percentile];
    const dates = rows.map(row => row.month);
    const mobile = width < 700;
    const years = [...new Set(dates.map(month => month.slice(0, 4)))];
    const capacity = Math.max(1, Math.floor((width - (mobile ? 56 : 138)) / (mobile ? 32 : 31)));
    const step = Math.max(1, Math.ceil(years.length / (mobile ? Math.min(capacity, 10) : capacity)));
    const firstIndexes = new Map();
    dates.forEach((month, index) => { if (!firstIndexes.has(month.slice(0, 4))) firstIndexes.set(month.slice(0, 4), index); });
    const monthIndex = month => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7));
    const short = monthIndex(dates.at(-1)) - monthIndex(dates[0]) < 12;
    const endLabel = text => ({ show: !mobile, formatter: () => text, color: '#4b5563', fontFamily: font, fontSize: 10, distance: 6 });
    const band = (low, high, stack, opacity, z) => [{
      name: low, type: 'line', data: rows.map(row => row[low]),
      lineStyle: { width: 0, opacity: 0 }, showSymbol: false, stack, stackStrategy: 'all', silent: true
    }, {
      name: high, type: 'line', data: rows.map(row => row[high] - row[low]),
      lineStyle: { width: 0, opacity: 0 }, showSymbol: false, stack, stackStrategy: 'all',
      areaStyle: { color: gradient(opacity) }, silent: true, z, endLabel: endLabel(high)
    }];
    // Additive ECharts stacks distort bands on a log axis. Project each interval's
    // real endpoints instead, omitting intervals with a nonpositive boundary.
    const logBand = (low, high, name, opacity, z) => ({
      name: name + '-band', type: 'custom', silent: true, z,
      dimensions: ['segment', 'lower', 'upper', 'nextLower', 'nextUpper'],
      encode: { x: 'segment', y: ['lower', 'upper', 'nextLower', 'nextUpper'] },
      data: rows.slice(0, -1).flatMap((row, index) =>
        row[low] > 0 && rows[index + 1][low] > 0 ?
          [[index, row[low], row[high], rows[index + 1][low], rows[index + 1][high]]] : []),
      renderItem: (params, api) => {
        const index = api.value(0);
        const next = index + 1;
        return { type: 'polygon', shape: { points: [
          api.coord([index, rows[index][low]]), api.coord([index, rows[index][high]]),
          api.coord([next, rows[next][high]]), api.coord([next, rows[next][low]])
        ] }, style: { fill: gradient(opacity) } };
      }
    });
    const logBoundary = p => ({
      name: p, type: 'line', data: rows.map(row => value(row, p)),
      lineStyle: { width: 0, opacity: 0 }, showSymbol: false, silent: true, endLabel: ['p90', 'p75'].includes(p) ? endLabel(p) : { show: false }
    });
    const median = {
      name: t('Median'), type: 'line', data: rows.map(row => value(row, 'p50')),
      showSymbol: false, z: 10, lineStyle: { width: 2.5, color: blue }, itemStyle: { color: blue },
      endLabel: { show: !mobile, formatter: params => money(Number(params.value)), color: '#ffffff',
        backgroundColor: blue, padding: [3, 6], borderRadius: 5, fontFamily: font,
        fontSize: 11, fontWeight: 'bold', distance: 6 },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: muted, type: 'dashed', width: 1 },
        data: input.goals.map((goal, index) => ({ xAxis: goal.month,
          label: { show: true, formatter: String(goal.number), position: 'insideEndTop', rotate: 0,
            // Stagger coincident goals while keeping the saved numbering.
            offset: [0, input.goals.slice(0, index).filter(other => other.month === goal.month).length * 16],
            color: muted, fontFamily: font, fontSize: mobile ? 10 : 11 } })) }
    };
    const labels = ['p10', 'p25'].map(p => ({
      name: p + '-label', type: 'scatter', data: [[dates.length - 1, value(rows.at(-1), p)]],
      symbolSize: 0, silent: true, label: { ...endLabel(p), position: 'right' }
    }));
    return {
      animation: false, backgroundColor: '#ffffff',
      title: { text: t(key === 'portfolio' ? 'Portfolio forecast' : 'Net capital forecast') + ` (${input.currency})` + (logarithmic ? ' · ' + t('Logarithmic scale') : ''),
        left: mobile ? 12 : 18, top: mobile ? 12 : 16,
        textStyle: { fontFamily: font, fontSize: mobile ? 14 : 15, fontWeight: 'bold', color: '#111827' } },
      grid: { left: mobile ? 8 : 16, right: mobile ? 14 : 74,
        top: mobile ? 66 : 76, bottom: mobile ? 22 : 26, containLabel: true },
      xAxis: { type: 'category', data: dates, boundaryGap: false, axisLine: { show: false },
        axisTick: { show: false }, splitLine: { show: false },
        axisLabel: { color: muted, fontFamily: font, fontSize: mobile ? 10 : 11, hideOverlap: true, interval: 0,
          alignMinLabel: 'left', alignMaxLabel: 'right',
          formatter: (value, index) => {
            if (short) return monthLabel(value);
            const year = value.slice(0, 4);
            return index === firstIndexes.get(year) && (years.length - 1 - years.indexOf(year)) % step === 0 ? year : '';
          } } },
      yAxis: { type: logarithmic ? 'log' : 'value', position: 'right', scale: true, name: input.currency,
        min: logarithmic ? Math.min(...rows.flatMap(row =>
          ['p10', 'p25', 'p50', 'p75', 'p90'].map(p => row[p]).filter(number => number > 0))) : undefined,
        axisLine: { show: false, onZero: false }, axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: '#eceef2' } },
        axisLabel: { color: muted, fontFamily: font, fontSize: mobile ? 10 : 11,
          showMinLabel: !logarithmic, formatter: value => numberFormat.format(value) } },
      series: [...(logarithmic ? [logBand('p10', 'p90', 'outer', 0.12, 1),
        logBand('p25', 'p75', 'inner', 0.25, 2), logBoundary('p90'), logBoundary('p75'), logBoundary('p25'), logBoundary('p10')] :
        [...band('p10', 'p90', 'outer', 0.12, 1), ...band('p25', 'p75', 'inner', 0.25, 2)]), median, ...labels],
      tooltip: { trigger: 'axis', confine: true, backgroundColor: '#ffffff', borderColor: 'rgba(0,0,0,0.08)',
        borderWidth: 1, padding: [8, 12], textStyle: { color: '#111827', fontFamily: font, fontSize: 12 },
        extraCssText: 'border-radius:10px;box-shadow:0 6px 24px rgba(16,24,40,0.14);font-variant-numeric:tabular-nums;',
        axisPointer: { type: 'line', lineStyle: { color: muted, width: 1, type: 'dashed' } },
        formatter: params => {
          const index = dates.indexOf(params[0]?.axisValue);
          if (index < 0) return '';
          const row = rows[index];
          return `<strong>${monthLabel(row.month)}</strong><br>` + ['p90', 'p75', 'p50', 'p25', 'p10'].map(p =>
            p === 'p50' ? `<strong>${t('Median')}: ${money(row[p])}</strong>` : `${p}: ${money(row[p])}`).join('<br>');
        } }
    };
  }

  function svg(key, width, height) {
    const exported = echarts.init(null, undefined, { renderer: 'svg', ssr: true, width, height });
    try {
      exported.setOption(option(key, width));
      return exported.renderToSVGString({ useViewBox: true });
    } finally { exported.dispose(); }
  }

  for (const key of ['portfolio', 'capital']) {
    scales.set(key, input.logarithmic === true);
    const host = document.getElementById(key);
    if (input.render) {
      host.style.width = input.render.width + 'px';
      host.style.height = input.render.height + 'px';
    }
    const chart = echarts.init(host, undefined, { renderer: 'canvas' });
    charts.set(key, chart);
    chart.setOption(option(key, host.clientWidth));
    if (!input.render) {
      new ResizeObserver(() => {
        chart.resize();
        chart.setOption(option(key, host.clientWidth), { notMerge: true });
      }).observe(host);
    }
  }

  document.querySelectorAll('[data-scale]').forEach(toggle => {
    const key = toggle.dataset.scale;
    const rows = input.charts[key];
    const note = document.getElementById(key + '-scale-note');
    const hasPositive = rows.some(row => row.p90 > 0);
    toggle.disabled = !hasPositive;
    toggle.checked = scales.get(key) === true;
    if (!hasPositive) {
      note.hidden = false;
      note.textContent = t('Logarithmic scale is unavailable: this forecast has no positive values.');
    }
    toggle.addEventListener('change', () => {
      scales.set(key, toggle.checked);
      const chart = charts.get(key);
      chart.setOption(option(key, document.getElementById(key).clientWidth), { notMerge: true });
      note.hidden = !toggle.checked || !rows.some(row => row.p10 <= 0);
      note.textContent = t('Zero and negative values are omitted on the logarithmic scale; affected bands have gaps.');
    });
    if (toggle.checked && rows.some(row => row.p10 <= 0)) {
      note.hidden = false;
      note.textContent = t('Zero and negative values are omitted on the logarithmic scale; affected bands have gaps.');
    }
    const annotations = document.getElementById(key + '-goals');
    for (const goal of input.goals) {
      const item = document.createElement('li');
      item.textContent = `${goal.number} — ${goal.label} (${monthLabel(goal.month)})`;
      annotations.appendChild(item);
    }
  });

  document.querySelectorAll('button[data-chart]').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.dataset.chart;
      const chart = charts.get(key);
      const isSvg = button.dataset.format === 'svg';
      const content = isSvg ? svg(key, chart.getWidth(), chart.getHeight()) :
        chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
      const url = isSvg ? URL.createObjectURL(new Blob([content], { type: 'image/svg+xml' })) : content;
      const link = document.createElement('a');
      link.download = key + '.' + button.dataset.format;
      link.href = url;
      link.click();
      if (isSvg) setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  });

  if (input.render) {
    const output = {};
    for (const [key, chart] of charts) {
      output[key] = input.render.format === 'svg' ? svg(key, chart.getWidth(), chart.getHeight()) :
        chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }).split(',')[1];
    }
    document.getElementById('render-output').textContent = JSON.stringify(output);
  }
})();
