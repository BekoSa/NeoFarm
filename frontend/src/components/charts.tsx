import { useRef, useState } from "react";

// Theme-matched status hexes (same meaning as StatusPill / Dashboard).
export const C = {
  accepted: "#34d399",
  rejected: "#f87171",
  queued: "#fde047",
  dedup: "#c084fc",
  expired: "#9ca3af",
  error: "#f472b6",
  grid: "#2a313a",
  muted: "#8a93a3",
  ink: "#e5e7eb",
};

export interface Series {
  label: string;
  color: string;
  values: number[];
  dashed?: boolean;
}

/** Multi-series line chart, one y-axis, recessive grid, hover crosshair.
 *  Identity is never colour-alone: legend + end labels, and callers can set
 *  `dashed` as a second encoding for a CVD-risky pair (e.g. green/red). */
export function LineChart({
  series, height = 170, unit = "", fmt = (v: number) => String(v),
}: {
  series: Series[];
  height?: number;
  unit?: string;
  fmt?: (v: number) => string;
}) {
  const W = 600;
  const H = height;
  const padL = 40, padR = 52, padT = 10, padB = 18;
  const n = Math.max(0, ...series.map((s) => s.values.length));
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);

  if (n < 2) {
    return <div className="text-muted text-sm h-[120px] grid place-items-center">collecting data…</div>;
  }

  const vals = series.flatMap((s) => s.values);
  const maxV = Math.max(1, ...vals);
  const minV = Math.min(0, ...vals);
  const span = maxV - minV || 1;
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - minV) / span) * (H - padT - padB);
  const path = (s: Series) =>
    s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");

  const ticks = [maxV, minV + span / 2, minV];
  const idx = hover == null ? n - 1 : hover;

  const onMove = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((mx - padL) / (W - padL - padR)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mb-1 text-xs">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5 text-muted">
            <svg width="16" height="8">
              <line x1="0" y1="4" x2="16" y2="4" stroke={s.color} strokeWidth="2"
                    strokeDasharray={s.dashed ? "3 2" : undefined} />
            </svg>
            {s.label} <span className="mono" style={{ color: s.color }}>
              {fmt(s.values[idx] ?? 0)}{unit}
            </span>
          </span>
        ))}
      </div>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
           onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           style={{ display: "block" }}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke={C.grid} strokeWidth="1" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize="9" fill={C.muted}>
              {fmt(Math.round(t))}
            </text>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.label} d={path(s)} fill="none" stroke={s.color} strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round"
                strokeDasharray={s.dashed ? "4 3" : undefined} />
        ))}
        {hover != null && (
          <line x1={x(idx)} x2={x(idx)} y1={padT} y2={H - padB} stroke={C.muted}
                strokeWidth="1" strokeDasharray="2 2" />
        )}
        {series.map((s) => (
          <circle key={s.label} cx={x(idx)} cy={y(s.values[idx] ?? 0)} r="3"
                  fill={s.color} stroke="#171a1f" strokeWidth="1.5" />
        ))}
        {series.map((s) => (
          <text key={s.label} x={W - padR + 4} y={y(s.values[n - 1] ?? 0) + 3}
                fontSize="9" fill={s.color} className="mono">
            {fmt(s.values[n - 1] ?? 0)}
          </text>
        ))}
      </svg>
    </div>
  );
}

/** Horizontal bar list for a ranked magnitude (top sploits/teams). */
export function BarList({
  rows, color, max, empty = "no data",
}: {
  rows: { label: string; value: number }[];
  color: string;
  max?: number;
  empty?: string;
}) {
  if (rows.length === 0) return <div className="text-muted text-sm">{empty}</div>;
  const m = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs" title={`${r.label}: ${r.value}`}>
          <div className="w-28 truncate mono text-muted">{r.label}</div>
          <div className="flex-1 bg-panel2 rounded h-3.5 overflow-hidden">
            <div className="h-3.5 rounded" style={{ width: `${(r.value / m) * 100}%`, background: color }} />
          </div>
          <div className="w-12 text-right mono">{r.value}</div>
        </div>
      ))}
    </div>
  );
}

/** Donut for a part-to-whole (status composition). Hero total in the hole;
 *  identity never colour-alone — the caller pairs it with a labelled+valued
 *  legend, and arcs carry a native tooltip. `active` is controlled so hovering
 *  a legend row and an arc highlight each other. A 2px surface gap separates
 *  adjacent fills. */
export function Donut({
  segments, size = 140, thickness = 16, total, centerLabel = "Total", active, onActive,
}: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
  total: number;
  centerLabel?: string;
  active?: string | null;
  onActive?: (label: string | null) => void;
}) {
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const gap = total > 0 ? 3 : 0;
  const drawn = segments.filter((s) => s.value > 0);
  let acc = 0;
  const activeSeg = active ? segments.find((s) => s.label === active) : undefined;
  const centerVal = activeSeg ? activeSeg.value : total;
  const centerTxt = activeSeg ? activeSeg.label : centerLabel;
  const pct = activeSeg && total ? Math.round((activeSeg.value / total) * 100) : null;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={c} cy={c} r={r} fill="none" stroke={C.grid} strokeWidth={thickness} />
        {drawn.map((s) => {
          const frac = s.value / total;
          const len = Math.max(0.5, frac * circ - gap);
          const start = acc * 360 - 90;
          acc += frac;
          const isActive = active === s.label;
          return (
            <circle
              key={s.label}
              cx={c} cy={c} r={r} fill="none"
              stroke={s.color}
              strokeWidth={isActive ? thickness + 4 : thickness}
              strokeDasharray={`${len} ${circ - len}`}
              transform={`rotate(${start} ${c} ${c})`}
              onMouseEnter={() => onActive?.(s.label)}
              onMouseLeave={() => onActive?.(null)}
              style={{ cursor: "pointer", transition: "stroke-width .12s" }}
            >
              <title>{s.label}: {s.value}{total ? ` (${Math.round(frac * 100)}%)` : ""}</title>
            </circle>
          );
        })}
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center pointer-events-none">
        <div>
          <div className="text-2xl font-bold mono" style={{ color: activeSeg?.color ?? C.ink }}>
            {centerVal.toLocaleString()}
          </div>
          <div className="text-xs text-muted">
            {centerTxt}{pct != null ? ` · ${pct}%` : ""}
          </div>
        </div>
      </div>
    </div>
  );
}
