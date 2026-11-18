/**
 * Charts for summary screens, drawn as plain SVG (no chart library): columns (stacked or side by side), ranked
 * horizontal bars, lines, and a ring for shares. Several series get a legend and fixed colours; every mark answers
 * the pointer and the keyboard with its value. Part of the design-system boundary, so the look changes in one place.
 */
import { showAmount, showPercent } from '../format';
import { useEffect, useRef, useState, type ReactNode } from 'react';

export type ChartKind = 'bar' | 'line' | 'pie';
export type ChartSeries = { name: string; values: readonly (number | null)[] };
export type ChartProps = { kind: ChartKind; categories: readonly string[]; series: readonly ChartSeries[];
  /** What the numbers are, e.g. '수주 금액'. */ name: string;
  /** Bars lying down, largest first: for names (customers, items) rather than a run of dates. */ ranked?: boolean;
  /** Several series in one column (for sums and counts); otherwise they stand side by side. */ stacked?: boolean;
  /** A mark to reach on each bar (a plan, a target): drawn as a line across the bar, with how far the bar got. One series only. */
  targets?: readonly (number | null)[]; targetName?: string;
  /** The mark is a part of the bar (shipped out of ordered) rather than a goal for it: the rate is mark / bar, called 진행률. */ markIsPart?: boolean;
  /** A series that is only there to compare with (the period before): drawn in grey beside the real one. */ muted?: number;
  height?: number };

const SLOTS = 8;                        // the palette has eight validated colours; a ninth series is folded into "기타"
const full = (value: number) => showAmount(value);
const compact = new Intl.NumberFormat('ko', { notation: 'compact', maximumFractionDigits: 1 });
const short = (label: string, length: number) => (label.length > length ? label.slice(0, length - 1) + '…' : label);
/** A round number at or above the largest value, in four steps. */
function scale(top: number) {
  if (top <= 0) return { max: 1, ticks: [0, 1] };
  const power = Math.pow(10, Math.floor(Math.log10(top))), unit = [1, 2, 2.5, 5, 10].map(step => step * power).find(step => step * 4 >= top) ?? power * 10;
  return { max: unit * 4, ticks: [0, 1, 2, 3, 4].map(step => step * unit) };
}
/** At most eight series: the rest are added up as "기타" (never a made-up ninth colour). */
function capped(series: readonly ChartSeries[]): ChartSeries[] {
  if (series.length <= SLOTS) return [...series];
  const rest = series.slice(SLOTS - 1);
  return [...series.slice(0, SLOTS - 1), { name: `기타 (${rest.length})`, values: series[0].values.map((_, index) => rest.reduce((sum, item) => sum + (item.values[index] ?? 0), 0)) }];
}

type Tip = { x: number; y: number; title: string; rows: { name?: string; value: string; color?: string }[] };

export function Chart({ kind, categories, series: given, name, ranked, stacked, targets, targetName = '계획', markIsPart, muted, height = 280 }: ChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(880);
  const [tip, setTip] = useState<Tip | null>(null);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(360, Math.floor(element.clientWidth))));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const series = capped(given);
  const many = series.length > 1;
  const color = (index: number) => (index === muted ? 'var(--chart-quiet)' : `var(--chart-${((muted !== undefined && index > muted ? index - 1 : index) % SLOTS) + 1})`);
  const goal = !many && targets ? targets : undefined;
  const reached = (value: number | null | undefined, target: number | null | undefined) => markIsPart ? (value ? showPercent(((target ?? 0) / value) * 100) : '-') : (target ? showPercent(((value ?? 0) / target) * 100) : '-');
  const rateName = markIsPart ? '진행률' : '달성률';
  const point = (event: { clientX: number; clientY: number }) => { const frame = box.current?.getBoundingClientRect(); return { x: event.clientX - (frame?.left ?? 0), y: event.clientY - (frame?.top ?? 0) }; };
  const leave = () => { setTip(null); setActive(null); };
  const label = `${name} ${kind === 'pie' ? '원' : kind === 'line' ? '선' : '막대'} 차트`;
  const legend = (many || goal) && <ul className="fw-chart-legend" aria-label="범례">{series.map((item, index) =>
    <li key={item.name}><span className={kind === 'line' ? 'fw-chart-key is-line' : 'fw-chart-key'} style={{ background: color(index) }} />{item.name}</li>)}
    {goal && <li><span className="fw-chart-key is-goal" />{targetName}</li>}</ul>;
  const frame = (body: ReactNode, tall: number) => <div className="fw-chart" data-ui="chart" data-kind={kind} ref={box} onMouseLeave={leave}>
    {legend}
    <svg width={width} height={tall} viewBox={`0 0 ${width} ${tall}`} role="img" aria-label={label}>{body}</svg>
    {tip && <div className="fw-chart-tip" role="status" style={{ left: Math.min(tip.x + 14, width - 190), top: Math.max(tip.y - 12, 0) }}>
      <div className="fw-chart-tip-title">{tip.title}</div>
      {tip.rows.map((row, index) => <div key={index} className="fw-chart-tip-row">{row.color && <span className="fw-chart-key is-line" style={{ background: row.color }} />}
        <strong>{row.value}</strong>{row.name && <span>{row.name}</span>}</div>)}
    </div>}
  </div>;
  if (!categories.length) return <div className="fw-chart-empty" data-ui="chart" data-kind={kind} ref={box}>조회된 자료가 없습니다.</div>;
  const totals = categories.map((_, index) => series.reduce((sum, item) => sum + Math.max(item.values[index] ?? 0, 0), 0));
  const rowsAt = (index: number): Tip['rows'] => [...series.map((item, at) => ({ name: many || goal ? item.name : undefined, value: item.values[index] === null || item.values[index] === undefined ? '-' : full(item.values[index] as number), color: many ? color(at) : undefined })),
    ...(goal ? [{ name: targetName, value: goal[index] === null || goal[index] === undefined ? '-' : full(goal[index] as number) }, { name: rateName, value: reached(series[0].values[index], goal[index]) }] : [])];

  // A ring for shares: at most six parts (the rest as 기타), the whole in the middle, names and figures beside it.
  if (kind === 'pie') {
    const parts = categories.map((category, index) => ({ name: category, value: totals[index] })).filter(part => part.value > 0).sort((a, b) => b.value - a.value);
    const shown = parts.length > 6 ? [...parts.slice(0, 5), { name: `기타 (${parts.length - 5})`, value: parts.slice(5).reduce((sum, part) => sum + part.value, 0) }] : parts;
    const whole = shown.reduce((sum, part) => sum + part.value, 0) || 1, radius = Math.min(height, 260) / 2 - 14, inner = radius * 0.6, cx = radius + 18, cy = height / 2;
    // In a narrow panel the names and figures go under the ring instead of beside it.
    const under = width < radius * 2 + 330, listX = under ? 18 : radius * 2 + 54, listY = (index: number) => (under ? height + 6 + index * 20 : Math.max(cy - shown.length * 11, 14) + index * 22);
    const figureX = under ? width - 76 : Math.min(width - radius * 2 - 70, 380);
    let angle = -Math.PI / 2;
    const arc = (from: number, to: number) => {
      const at = (r: number, a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`, wide = to - from > Math.PI ? 1 : 0;
      return to - from >= Math.PI * 2 - 0.0001
        ? `M ${cx - radius},${cy} a ${radius},${radius} 0 1,1 ${radius * 2},0 a ${radius},${radius} 0 1,1 ${-radius * 2},0 M ${cx - inner},${cy} a ${inner},${inner} 0 1,0 ${inner * 2},0 a ${inner},${inner} 0 1,0 ${-inner * 2},0`
        : `M ${at(radius, from)} A ${radius},${radius} 0 ${wide},1 ${at(radius, to)} L ${at(inner, to)} A ${inner},${inner} 0 ${wide},0 ${at(inner, from)} Z`;
    };
    return frame(<>
      {shown.map((part, index) => { const from = angle, to = angle + (part.value / whole) * Math.PI * 2; angle = to;
        const text = { title: part.name, rows: [{ value: full(part.value) }, { value: showPercent((part.value / whole) * 100), name: '비중' }] };
        return <path key={part.name} d={arc(from, to)} fill={color(index)} fillRule="evenodd" className="fw-chart-mark" opacity={active === null || active === index ? 1 : 0.5} tabIndex={0}
          onMouseMove={event => { setActive(index); setTip({ ...point(event), ...text }); }} onFocus={() => { setActive(index); setTip({ x: cx + radius, y: cy - radius, ...text }); }} onBlur={leave} />; })}
      <text x={cx} y={cy - 4} textAnchor="middle" className="fw-chart-hero">{compact.format(whole)}</text>
      <text x={cx} y={cy + 14} textAnchor="middle" className="fw-chart-text">{name}</text>
      {shown.map((part, index) => <g key={part.name} transform={`translate(${listX}, ${listY(index)})`} opacity={active === null || active === index ? 1 : 0.5}>
        <rect width={10} height={10} y={-9} rx={2} fill={color(index)} />
        <text x={18} className="fw-chart-label">{short(part.name, Math.max(Math.floor((figureX - 100) / 9), 6))}</text>
        <text x={figureX} textAnchor="end" className="fw-chart-value">{full(part.value)}</text>
        <text x={figureX + 54} textAnchor="end" className="fw-chart-text">{showPercent((part.value / whole) * 100)}</text></g>)}
    </>, under ? height + shown.length * 20 + 8 : height);
  }

  // Bars lying down, largest first: names read in full and close values compare on one baseline.
  if (kind === 'bar' && ranked && !many) {
    const order = categories.map((category, index) => ({ category, value: series[0].values[index] ?? 0, target: goal?.[index] ?? null })).sort((a, b) => b.value - a.value);
    const rows = order.slice(0, 15), left = Math.min(220, Math.max(90, width * 0.26)), right = 76, row = 26, top = 6;
    const { max } = scale(Math.max(...rows.map(item => Math.max(item.value, item.target ?? 0)), 0)), span = width - left - right;
    return frame(<>
      {rows.map((item, index) => { const length = Math.max((Math.max(item.value, 0) / max) * span, 1), y = top + index * row;
        const text = { title: item.category, rows: [{ value: full(item.value), name: goal ? name : undefined }, ...(item.target !== null ? [{ value: full(item.target), name: targetName }, { value: reached(item.value, item.target), name: rateName }] : [])] };
        return <g key={item.category} className="fw-chart-mark" tabIndex={0} opacity={active === null || active === index ? 1 : 0.55}
          onMouseMove={event => { setActive(index); setTip({ ...point(event), ...text }); }} onFocus={() => { setActive(index); setTip({ x: left + length, y, ...text }); }} onBlur={leave}>
          <rect x={0} y={y} width={width} height={row} fill="transparent" />
          <text x={left - 8} y={y + row / 2 + 4} textAnchor="end" className="fw-chart-label">{short(item.category, Math.floor(left / 8))}</text>
          <path d={`M ${left},${y + 6} h ${Math.max(length - 4, 0)} a 4,4 0 0 1 4,4 v 6 a 4,4 0 0 1 -4,4 h ${-Math.max(length - 4, 0)} Z`} fill={color(0)} />
          {item.target !== null && <line x1={left + (item.target / max) * span} x2={left + (item.target / max) * span} y1={y + 2} y2={y + row - 2} className="fw-chart-goal" />}
          <text x={Math.max(left + length, item.target !== null ? left + (item.target / max) * span : 0) + 6} y={y + row / 2 + 4} className="fw-chart-value">{full(item.value)}{item.target ? ` (${reached(item.value, item.target)})` : ''}</text></g>; })}
      <line x1={left} x2={left} y1={top} y2={top + rows.length * row} className="fw-chart-axis" />
      {order.length > rows.length && <text x={left} y={top + rows.length * row + 14} className="fw-chart-text">{`외 ${order.length - rows.length}건은 위 표에 있습니다`}</text>}
    </>, top + rows.length * row + (order.length > rows.length ? 22 : 6));
  }

  const left = 56, right = 20, top = 16, bottom = 30, plotW = width - left - right, plotH = height - top - bottom, band = plotW / categories.length;
  const stack = kind === 'bar' && many && stacked;
  const { max, ticks } = scale(Math.max(...(stack ? totals : series.flatMap(item => item.values.map(value => value ?? 0))), ...(goal ?? []).map(value => value ?? 0), 0));
  const y = (value: number) => top + plotH - (Math.max(value, 0) / max) * plotH;
  const tick = (value: number) => (max >= 10000 ? compact.format(value) : full(value));
  const every = Math.ceil(categories.length / Math.max(Math.floor(plotW / 74), 1));     // only as many names as fit side by side
  const axis = <>
    {ticks.map(value => <g key={value}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className={value === 0 ? 'fw-chart-axis' : 'fw-chart-grid'} />
      <text x={left - 8} y={y(value) + 4} textAnchor="end" className="fw-chart-tick">{tick(value)}</text></g>)}
    {categories.map((category, index) => index % every === 0 && <text key={index} x={left + index * band + band / 2} y={height - bottom + 17} textAnchor="middle" className="fw-chart-text">{short(category, Math.max(Math.floor((band * every) / 8), 6))}</text>)}
  </>;
  // One wide, invisible column per category takes the pointer: nobody has to land on a thin mark.
  const zones = categories.map((category, index) => <rect key={index} x={left + index * band} y={top} width={band} height={plotH + bottom} fill="transparent" tabIndex={0} className="fw-chart-zone" aria-label={`${category}: ${rowsAt(index).map(row => [row.name, row.value].filter(Boolean).join(' ')).join(', ')}`}
    onMouseMove={event => { setActive(index); setTip({ ...point(event), title: category, rows: rowsAt(index) }); }}
    onFocus={() => { setActive(index); setTip({ x: left + index * band + band / 2, y: top, title: category, rows: rowsAt(index) }); }} onBlur={leave} />);

  if (kind === 'line') {
    const x = (index: number) => left + index * band + band / 2;
    return frame(<>
      {axis}
      {active !== null && <line x1={x(active)} x2={x(active)} y1={top} y2={top + plotH} className="fw-chart-cross" />}
      {series.map((item, at) => { const dots = item.values.map((value, index) => ({ value, index })).filter(dot => dot.value !== null && dot.value !== undefined) as { value: number; index: number }[];
        const path = dots.map((dot, index) => `${index ? 'L' : 'M'} ${x(dot.index)},${y(dot.value)}`).join(' ');
        const last = dots[dots.length - 1], peak = dots.reduce((best, dot) => (dot.value > best.value ? dot : best), dots[0]);
        return <g key={item.name}>
          {!many && dots.length > 1 && <path d={`${path} L ${x(last.index)},${top + plotH} L ${x(dots[0].index)},${top + plotH} Z`} fill={color(at)} opacity={0.1} />}
          <path d={path} fill="none" stroke={color(at)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {dots.map(dot => (dots.length <= 24 || dot.index === active) && <circle key={dot.index} cx={x(dot.index)} cy={y(dot.value)} r={dot.index === active ? 5 : 4} fill={color(at)} className="fw-chart-dot" />)}
          {/* Only the ends and the peak are written out; the axis and the pointer give the rest. */}
          {last && series.length <= 4 && <text x={Math.min(x(last.index) + 8, width - 4)} y={y(last.value) + 4} textAnchor={x(last.index) + 60 > width ? 'end' : 'start'} dy={x(last.index) + 60 > width ? -12 : 0} className="fw-chart-value">{full(last.value)}</text>}
          {!many && peak && peak !== last && <text x={x(peak.index)} y={y(peak.value) - 9} textAnchor="middle" className="fw-chart-value">{full(peak.value)}</text>}
        </g>; })}
      {zones}
    </>, height);
  }

  // Columns: one series, or several stacked (sums, counts) or side by side (averages and the like).
  const count = stack || !many ? 1 : series.length, thick = Math.min(24, Math.max((band * 0.72 - (count - 1) * 2) / count, 2)), group = thick * count + (count - 1) * 2;
  const column = (xAt: number, from: number, to: number, fill: string, key: string, round: boolean) => {
    const high = Math.max(from - to, 0), r = round ? Math.min(4, high, thick / 2) : 0;
    return high <= 0 ? null : <path key={key} fill={fill} d={`M ${xAt},${from} v ${-(high - r)} a ${r},${r} 0 0 1 ${r},${-r} h ${thick - r * 2} a ${r},${r} 0 0 1 ${r},${r} v ${high - r} Z`} />;
  };
  return frame(<>
    {axis}
    {categories.map((_, index) => { const start = left + index * band + (band - group) / 2; let base = top + plotH;
      return <g key={index} opacity={active === null || active === index ? 1 : 0.55}>
        {series.map((item, at) => { const value = Math.max(item.values[index] ?? 0, 0);
          if (stack) { const from = base, to = base - (value / max) * plotH; base = to - (value > 0 ? 2 : 0);      // a 2px gap of the surface keeps the parts apart
            const topmost = series.slice(at + 1).every(next => (next.values[index] ?? 0) <= 0);
            return column(start, from, Math.min(to + (at ? 0 : 0), from), color(at), item.name, topmost); }
          return column(start + at * (thick + 2), top + plotH, y(value), color(at), item.name, true); })}
        {/* The figure is written on a column only while there is room for it. */}
        {(stack || !many) && categories.length <= 14 && totals[index] > 0 && <text x={left + index * band + band / 2} y={Math.min(y(totals[index]), goal?.[index] ? y(goal[index] as number) : Infinity) - 6 - (stack ? (series.filter(item => (item.values[index] ?? 0) > 0).length - 1) * 2 : 0)} textAnchor="middle" className="fw-chart-value">{max >= 100000 ? compact.format(totals[index]) : full(totals[index])}</text>}
      </g>; })}
    {goal && categories.map((_, index) => goal[index] !== null && goal[index] !== undefined && <line key={`goal${index}`} x1={left + index * band + (band - thick) / 2 - 7} x2={left + index * band + (band + thick) / 2 + 7} y1={y(goal[index] as number)} y2={y(goal[index] as number)} className="fw-chart-goal" />)}
    {zones}
  </>, height);
}

/** A row of headline figures above a chart or table: the whole period in a few numbers. */
export function StatTiles({ items }: { items: readonly { label: string; value: number | null; note?: string; /** Shown instead of the plain number, e.g. '87.5%'. */ text?: string; tone?: 'up' | 'down' }[] }) {
  return <div className="fw-stats" data-ui="stat-tiles">{items.map(item => <div key={item.label} className="fw-stat">
    <div className="fw-stat-label">{item.label}</div>
    <div className="fw-stat-value" title={item.value === null ? undefined : full(item.value)}>{item.tone && <span className={`fw-stat-arrow is-${item.tone}`} aria-hidden="true">{item.tone === 'up' ? '▲' : '▼'}</span>}{item.text ?? (item.value === null ? '-' : Math.abs(item.value) >= 100000000 ? compact.format(item.value) : full(item.value))}</div>
    {item.note && <div className="fw-stat-note">{item.note}</div>}
  </div>)}</div>;
}
