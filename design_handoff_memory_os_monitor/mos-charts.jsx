/* Hermes Memory-OS — reusable SVG charts (theme-colored via props).
   No external libs. All deterministic from data. Exported to window. */

// ── Sparkline (tiny inline trend) ───────────────────────────
function Sparkline({ data, color, fill, w = 120, h = 34, strokeW = 1.6 }) {
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - 3 - ((v - min) / span) * (h - 6);
    return [x, y];
  });
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = d + ` L ${w} ${h} L 0 ${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} preserveAspectRatio="none" style={{ display: "block" }}>
      {fill && <path d={area} fill={fill} />}
      <path d={d} fill="none" stroke={color} strokeWidth={strokeW} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Area line chart with grid + axis ticks ──────────────────
function AreaLine({ data, color, fill, w = 520, h = 150, pad = 8, dots = false, baseline = 0 }) {
  const min = Math.min(baseline, ...data), max = Math.max(...data);
  const span = max - min || 1;
  const iw = w - pad * 2, ih = h - pad * 2;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * iw;
    const y = pad + ih - ((v - min) / span) * ih;
    return [x, y];
  });
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = d + ` L ${pad + iw} ${pad + ih} L ${pad} ${pad + ih} Z`;
  const grid = [0.25, 0.5, 0.75];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: "block" }}>
      {grid.map((g, i) => (
        <line key={i} x1={pad} x2={pad + iw} y1={pad + ih * g} y2={pad + ih * g}
          stroke="var(--grid)" strokeWidth="1" strokeDasharray="2 4" />
      ))}
      {fill && <path d={area} fill={fill} />}
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {dots && pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2.2" fill={color} />)}
    </svg>
  );
}

// ── Vertical bar series ─────────────────────────────────────
function BarSeries({ data, color, w = 520, h = 120, gap = 2 }) {
  const max = Math.max(...data) || 1;
  const n = data.length;
  const bw = (w - gap * (n - 1)) / n;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: "block" }}>
      {data.map((v, i) => {
        const bh = (v / max) * (h - 4);
        return <rect key={i} x={i * (bw + gap)} y={h - bh} width={bw} height={bh} rx="1.5" fill={color} />;
      })}
    </svg>
  );
}

// ── Horizontal stacked bar (single row, segments) ───────────
function StackBar({ segments, h = 12, radius = 6 }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let x = 0;
  return (
    <svg viewBox={`0 0 100 ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: "block", borderRadius: radius, overflow: "hidden" }}>
      {segments.map((s, i) => {
        const wseg = (s.value / total) * 100;
        const rect = <rect key={i} x={x} y={0} width={wseg + 0.4} height={h} fill={s.color} />;
        x += wseg;
        return rect;
      })}
    </svg>
  );
}

// ── Donut / ring ────────────────────────────────────────────
function Donut({ segments, size = 132, thickness = 16, gap = 2, center }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--track)" strokeWidth={thickness} />
      {segments.map((s, i) => {
        const frac = s.value / total;
        const len = Math.max(0, frac * circ - gap);
        const el = (
          <circle key={i} cx={c} cy={c} r={r} fill="none" stroke={s.color} strokeWidth={thickness}
            strokeDasharray={`${len} ${circ - len}`} strokeDashoffset={-offset}
            transform={`rotate(-90 ${c} ${c})`} strokeLinecap="butt" />
        );
        offset += frac * circ;
        return el;
      })}
      {center && (
        <g>
          <text x={c} y={c - 2} textAnchor="middle" fontSize={size * 0.2} fontWeight="700"
            fill="var(--text)" style={{ fontFamily: "var(--mono)" }}>{center.value}</text>
          <text x={c} y={c + size * 0.13} textAnchor="middle" fontSize={size * 0.085}
            fill="var(--muted)" style={{ fontFamily: "var(--mono)", letterSpacing: ".05em" }}>{center.label}</text>
        </g>
      )}
    </svg>
  );
}

// ── Status gauge (semi-arc PASS/WARN/FAIL) ──────────────────
function Gauge({ pass, warn, fail, color, size = 220 }) {
  const total = pass + warn + fail || 1;
  const r = size * 0.4;
  const c = size / 2;
  const stroke = size * 0.075;
  // semicircle from 180deg to 360deg (top half)
  const arcLen = Math.PI * r; // half circle
  const segs = [
    { v: pass, col: "var(--pass)" },
    { v: warn, col: "var(--warn)" },
    { v: fail, col: "var(--fail)" },
  ];
  let off = 0;
  const cy = c + size * 0.13;
  return (
    <svg viewBox={`0 0 ${size} ${size * 0.62}`} width="100%" height={size * 0.62}>
      <path d={`M ${c - r} ${cy} A ${r} ${r} 0 0 1 ${c + r} ${cy}`} fill="none"
        stroke="var(--track)" strokeWidth={stroke} strokeLinecap="round" />
      {segs.map((s, i) => {
        const frac = s.v / total;
        const len = frac * arcLen;
        const el = (
          <path key={i} d={`M ${c - r} ${cy} A ${r} ${r} 0 0 1 ${c + r} ${cy}`} fill="none"
            stroke={s.col} strokeWidth={stroke}
            strokeDasharray={`${Math.max(0, len - 1.5)} ${arcLen}`} strokeDashoffset={-off}
            strokeLinecap="butt" />
        );
        off += len;
        return el;
      })}
    </svg>
  );
}

Object.assign(window, { Sparkline, AreaLine, BarSeries, StackBar, Donut, Gauge });
