// Shared primitives for v2

const HoverTip = ({ tip, children, className = '', style }) => (
  <div className={`hover-tip ${className}`} data-tip={tip || ''} style={style}>
    {children}
  </div>
);

const formatTipValue = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, '');
  return String(value);
};

const pointValue = (point) => typeof point === 'number' ? point : Number(point?.value ?? point?.weight_kg ?? 0);

const pointTip = (point, fallbackIndex) => {
  if (typeof point === 'number') return `第 ${fallbackIndex + 1} 点 · ${formatTipValue(point)}`;
  const label = point?.label || point?.date || `第 ${fallbackIndex + 1} 点`;
  const value = formatTipValue(point?.value ?? point?.weight_kg);
  const unit = point?.unit ? ` ${point.unit}` : point?.weight_kg !== undefined ? ' kg' : '';
  const note = point?.notes || point?.note || point?.title || '';
  return `${label} · ${value}${unit}${note ? ` · ${note}` : ''}`;
};

const Placeholder = ({ label, w = '100%', h = 80, style = {}, tooltip }) => (
  <HoverTip tip={tooltip || label} className="hover-tip-block">
    <div className="ph" style={{ width: w, height: h, ...style }}>{label}</div>
  </HoverTip>
);

const Chip = ({ children, variant, style }) => (
  <span className={`chip ${variant || ''}`} style={style}>{children}</span>
);

const Stamp = ({ children }) => <span className="stamp">{children}</span>;

const memberAvatarSrc = (member) => member?.avatar_url || '';

const Avatar = ({ label, size = 'md', ring = false, cat = false, src = '', alt = '', style }) => {
  const [failedSrc, setFailedSrc] = React.useState('');
  const showImage = Boolean(src) && src !== failedSrc;
  return (
    <div className={`avatar ${size} ${ring ? 'ring' : ''} ${cat ? 'cat' : ''} ${showImage ? 'has-image' : ''}`} style={style}>
      {showImage && <img className="avatar__image" src={src} alt={alt || label} onError={() => setFailedSrc(src)} />}
      <span className="avatar__label">{label}</span>
    </div>
  );
};

const Scribble = ({ children }) => <span className="scribble">{children}</span>;

const Btn = ({ children, primary, ghost, disabled, onClick, style, type = 'button' }) => (
  <button
    type={type}
    className={`btn ${primary ? 'primary' : ''} ${ghost ? 'ghost' : ''}`}
    onClick={onClick}
    disabled={disabled}
    style={style}
  >{children}</button>
);

/* 手绘线条小图标：与 QuickIcon 同款 1.8px 圆头线条，贴合纸面主题 */
const SketchIcon = ({ name }) => {
  if (name === 'stop') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <line x1="10" y1="9" x2="10" y2="15" />
        <line x1="14" y1="9" x2="14" y2="15" />
      </svg>
    );
  }
  if (name === 'delete-all') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        <circle cx="18.5" cy="18.5" r="4.4" fill="var(--paper)" stroke="none" />
        <line x1="18.5" y1="16.3" x2="18.5" y2="20.7" />
        <line x1="16.3" y1="18.5" x2="20.7" y2="18.5" />
      </svg>
    );
  }
  if (name === 'delete') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        <line x1="10" y1="11" x2="10" y2="17" />
        <line x1="14" y1="11" x2="14" y2="17" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
    </svg>
  );
};

const GLYPH_ICON = { '✎': 'edit', '🗑': 'delete', '🗑+': 'delete-all', '⏸': 'stop' };

const IconBtn = ({ children, title, danger, warn, onClick, style }) => (
  <button
    type="button"
    className={`icon-btn ${danger ? 'danger' : ''} ${warn ? 'warn' : ''}`}
    title={title || ''}
    aria-label={title || '操作'}
    onClick={onClick}
    style={style}
  >{GLYPH_ICON[children] ? <SketchIcon name={GLYPH_ICON[children]} /> : children}</button>
);

// Sketchy line chart
const LineChart = ({ points = [], w = 340, h = 80, color, refBand, labels, unit }) => {
  if (!points.length) return null;
  const values = points.map(pointValue);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const xy = (v, i) => [i * step, h - ((v - min) / span) * (h - 10) - 5];
  const d = values.map((v, i) => {
    const [x, y] = xy(v, i);
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
  return (
    <HoverTip tip="悬停点位查看详情" className="hover-tip-block">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: 'block', overflow: 'visible' }}>
      {refBand && (() => {
        const [lo, hi] = refBand;
        const y1 = h - ((hi - min) / span) * (h - 10) - 5;
        const y2 = h - ((lo - min) / span) * (h - 10) - 5;
        return <rect x={0} y={Math.min(y1, y2)} width={w} height={Math.abs(y2 - y1)} fill="var(--accent-2)" opacity="0.35" />;
      })()}
      <path d={d} fill="none" stroke={color || 'var(--ink)'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      {values.map((v, i) => {
        const [x, y] = xy(v, i);
        const tip = typeof points[i] === 'number' && unit
          ? `${labels?.[i] || `第 ${i + 1} 点`} · ${formatTipValue(v)} ${unit}`
          : pointTip(points[i], i);
        return (
          <circle
            key={i}
            className="chart-point"
            cx={x}
            cy={y}
            r="3.2"
            fill="var(--paper)"
            stroke={color || 'var(--ink)'}
            strokeWidth="1.5"
          >
            <title>{tip}</title>
          </circle>
        );
      })}
      </svg>
    </HoverTip>
  );
};

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const chartColor = (value, fallback) => {
  const cssMatch = String(value || '').match(/^var\((--[^)]+)\)$/);
  return cssMatch ? cssVar(cssMatch[1]) : (value || fallback);
};

const EChartLine = ({
  points = [],
  height = 240,
  unit = '',
  color,
  yName = '',
  emptyText = '暂无趋势数据',
  refBand,
  selectedKey,
  onPointClick,
}) => {
  const elRef = React.useRef(null);
  const chartRef = React.useRef(null);
  const optionKey = JSON.stringify(points);
  const refBandKey = JSON.stringify(refBand || null);

  React.useEffect(() => {
    if (!elRef.current || !window.echarts) return undefined;
    const chart = window.echarts.init(elRef.current, null, { renderer: 'canvas' });
    chartRef.current = chart;

    const ink = cssVar('--ink') || '#1f1b16';
    const inkSoft = cssVar('--ink-soft') || '#6b6354';
    const rule = cssVar('--rule') || '#d9cfb8';
    const paper = cssVar('--paper') || '#fffdf6';
    const accent = chartColor(color, cssVar('--accent') || '#d79a4a');
    const categories = points.map((p, i) => p.date || p.label || String(i + 1));
    const pointKey = (p) => String(p.id ?? p.date ?? p.label ?? '');
    const seriesData = points.map((p) => ({
      value: Number(p.value ?? p.weight_kg ?? 0),
      raw: p,
      itemStyle: selectedKey && pointKey(p) === String(selectedKey)
        ? { color: accent, borderColor: ink, borderWidth: 3, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.22)' }
        : undefined,
    }));
    const markArea = refBand ? {
      silent: true,
      itemStyle: { color: 'rgba(120, 170, 145, 0.16)' },
      data: [[{ yAxis: refBand[0], name: '参考范围' }, { yAxis: refBand[1] }]],
    } : undefined;

    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 420,
      grid: { top: 22, right: 18, bottom: points.length > 8 ? 56 : 34, left: 46, containLabel: true },
      tooltip: {
        trigger: 'axis',
        confine: true,
        appendToBody: true,
        backgroundColor: ink,
        borderColor: ink,
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: paper, fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
        axisPointer: {
          type: 'cross',
          lineStyle: { color: inkSoft, width: 1, type: 'dashed' },
          crossStyle: { color: inkSoft, width: 1, type: 'dashed' },
          label: { backgroundColor: ink, color: paper, fontSize: 10 },
        },
        formatter: (items) => {
          const item = items?.[0];
          const raw = item?.data?.raw || {};
          const value = Number(raw.value ?? raw.weight_kg ?? item?.value ?? 0);
          const index = item?.dataIndex ?? 0;
          const prevRaw = index > 0 ? points[index - 1] : null;
          const prev = prevRaw ? Number(prevRaw.value ?? prevRaw.weight_kg ?? 0) : null;
          const diff = prev === null ? '' : `<div style="opacity:.75;margin-top:3px">较上次 ${value - prev >= 0 ? '+' : ''}${(value - prev).toFixed(2)} ${unit}</div>`;
          const note = raw.notes || raw.note || raw.title || '';
          return [
            `<div style="font-weight:700;margin-bottom:4px">${raw.date || raw.label || item?.axisValue || ''}</div>`,
            `<div>${yName || '数值'} <b style="font-size:14px">${formatTipValue(value)}</b>${unit ? ` ${unit}` : ''}</div>`,
            diff,
            note ? `<div style="opacity:.75;margin-top:3px">${note}</div>` : '',
          ].join('');
        },
      },
      dataZoom: points.length > 8 ? [
        { type: 'inside', throttle: 50, zoomOnMouseWheel: true, moveOnMouseMove: true },
        {
          type: 'slider',
          height: 18,
          bottom: 12,
          borderColor: rule,
          fillerColor: 'rgba(107, 99, 84, 0.18)',
          handleStyle: { color: ink },
          textStyle: { color: inkSoft, fontFamily: 'JetBrains Mono, monospace', fontSize: 9 },
        },
      ] : [],
      xAxis: {
        type: 'category',
        data: categories,
        boundaryGap: false,
        axisLabel: {
          color: inkSoft,
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 10,
          formatter: (value) => String(value).slice(2, 10),
        },
        axisLine: { lineStyle: { color: ink } },
        axisTick: { lineStyle: { color: ink } },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        name: yName,
        nameTextStyle: { color: inkSoft, fontFamily: 'JetBrains Mono, monospace', fontSize: 10 },
        scale: true,
        axisLabel: { color: inkSoft, fontFamily: 'JetBrains Mono, monospace', fontSize: 10 },
        axisLine: { show: true, lineStyle: { color: ink } },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
      },
      series: [{
        name: yName || '趋势',
        type: 'line',
        data: seriesData,
        smooth: 0.28,
        symbol: 'circle',
        symbolSize: 7,
        showSymbol: true,
        lineStyle: { width: 3, color: accent },
        itemStyle: { color: paper, borderColor: accent, borderWidth: 2 },
        areaStyle: { color: 'rgba(215, 154, 74, 0.13)' },
        emphasis: { focus: 'series', itemStyle: { borderWidth: 3, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.18)' } },
        markArea,
      }],
      graphic: points.length ? [] : [{
        type: 'text',
        left: 'center',
        top: 'middle',
        style: { text: emptyText, fill: inkSoft, font: '14px Kalam, cursive' },
      }],
    }, true);

    const handleClick = (event) => {
      if (!onPointClick) return;
      const x = event.offsetX ?? event.zrX;
      const y = event.offsetY ?? event.zrY;
      if (x === undefined || y === undefined || !chart.containPixel({ gridIndex: 0 }, [x, y])) return;
      const [dataIndex] = chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, y]);
      const point = points[Math.max(0, Math.min(points.length - 1, Math.round(dataIndex)))];
      if (point) onPointClick(point);
    };
    chart.getZr().on('click', handleClick);

    const resize = () => chart.resize();
    const observer = window.ResizeObserver ? new ResizeObserver(resize) : null;
    observer?.observe(elRef.current);
    window.addEventListener('resize', resize);

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      chart.getZr().off('click', handleClick);
      chart.dispose();
      if (chartRef.current === chart) chartRef.current = null;
    };
  }, [optionKey, refBandKey, selectedKey, height, unit, color, yName, emptyText, onPointClick]);

  if (!window.echarts) {
    return <LineChart points={points} w={800} h={height} color={color} unit={unit} refBand={refBand} />;
  }

  return <div ref={elRef} className="echart-line" style={{ height, minHeight: height }} />;
};

const Bars = ({ values = [], w = 160, h = 60, color }) => {
  if (!values.length) return null;
  const bw = w / values.length - 4;
  const max = Math.max(...values);
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      {values.map((v, i) => (
        <rect key={i} x={i * (bw + 4)} y={h - (v / max) * h} width={bw} height={(v / max) * h}
              fill={color || 'var(--accent)'} stroke="var(--line)" strokeWidth="1.5" />
      ))}
    </svg>
  );
};

const DashLabel = ({ children, right }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0 8px' }}>
    <span className="mono" style={{ color: 'var(--ink-soft)', textTransform: 'uppercase', letterSpacing: '0.14em' }}>{children}</span>
    <div style={{ flex: 1, borderTop: '1.5px dashed var(--rule)' }} />
    {right && <span className="mono" style={{ color: 'var(--ink-soft)' }}>{right}</span>}
  </div>
);

const Tile = ({ k, v, u, warn, trend }) => (
  <div className={`tile ${warn ? 'warn' : ''}`}>
    <div className="k">{k}</div>
    <div className="v" style={warn ? { color: 'var(--danger)' } : {}}>{v}</div>
    {u && <div className="u">{u}</div>}
    {trend && <div style={{ marginTop: 4 }}><LineChart points={trend} w={120} h={28} color={warn ? 'var(--danger)' : 'var(--ink)'} /></div>}
  </div>
);

Object.assign(window, { HoverTip, Placeholder, Chip, Stamp, Avatar, memberAvatarSrc, Scribble, Btn, IconBtn, LineChart, EChartLine, Bars, DashLabel, Tile });
