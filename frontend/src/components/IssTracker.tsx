import { useQuery } from "@tanstack/react-query";

/** Live ISS tracker. Real position from wheretheiss.at (https + CORS, no key),
 *  refreshed every few seconds. With no internet (e.g. the game network) it
 *  falls back to the ISS's near-constant altitude/velocity and keeps the orbit
 *  animating. Purely cosmetic; self-contained. */

interface Iss {
  lat: number | null;
  lon: number | null;
  altKm: number;
  velKmh: number;
  visibility: string | null;
  live: boolean;
}

// Altitude and orbital speed barely vary, so these read true even offline.
const FALLBACK: Iss = {
  lat: null,
  lon: null,
  altKm: 420,
  velKmh: 27600,
  visibility: null,
  live: false,
};

async function fetchIss(): Promise<Iss> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 6000);
  try {
    const r = await fetch("https://api.wheretheiss.at/v1/satellites/25544", { signal: ctrl.signal });
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    return {
      lat: d.latitude,
      lon: d.longitude,
      altKm: Math.round(d.altitude),
      velKmh: Math.round(d.velocity),
      visibility: d.visibility ?? null,
      live: true,
    };
  } finally {
    clearTimeout(timer);
  }
}

function geo(v: number | null, pos: string, neg: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.abs(v).toFixed(1)}°${v >= 0 ? pos : neg}`;
}

// A fixed sprinkle of stars (deterministic so the scene doesn't jump on render).
const STARS = [
  { x: "12%", y: "22%", d: "2.6s" }, { x: "28%", y: "70%", d: "3.4s" },
  { x: "46%", y: "14%", d: "2.1s" }, { x: "63%", y: "60%", d: "3.9s" },
  { x: "80%", y: "28%", d: "2.8s" }, { x: "90%", y: "74%", d: "3.2s" },
  { x: "20%", y: "48%", d: "4.2s" }, { x: "72%", y: "40%", d: "2.4s" },
];

export function IssTracker() {
  const q = useQuery({
    queryKey: ["iss"],
    queryFn: fetchIss,
    retry: false,
    refetchInterval: 5_000,
    refetchOnWindowFocus: false,
  });
  const iss = q.data ?? FALLBACK;
  const sunlit = iss.visibility === "daylight";

  return (
    <section className="bg-panel border border-border rounded-xl h-full flex flex-col overflow-hidden">
      <style>{`
        @keyframes iss-orbit { to { transform: rotate(360deg); } }
        @keyframes iss-spin  { to { transform: rotate(360deg); } }
        @keyframes iss-twinkle { 0%,100% { opacity:.15 } 50% { opacity:.95 } }
        @keyframes iss-pulse {
          0%,100% { box-shadow: 0 0 6px 1px rgba(103,232,249,.7); }
          50%     { box-shadow: 0 0 12px 4px rgba(103,232,249,.95); }
        }
        @media (prefers-reduced-motion: reduce) { .iss-anim { animation: none !important; } }
      `}</style>

      <header className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="font-semibold flex items-center gap-2">
          <span>ISS</span>
          <span className="text-xs text-muted">· live orbit</span>
        </h2>
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <span
            className={"w-2 h-2 rounded-full " + (iss.live ? "bg-emerald-400" : "bg-amber-400")}
            title={iss.live ? "live from wheretheiss.at" : "no live feed — orbit simulated"}
          />
          {iss.live ? "tracking" : "offline"}
        </span>
      </header>

      <div className="p-4 flex items-center gap-5 flex-1">
        {/* orbital scene */}
        <div className="relative shrink-0 w-[128px] h-[128px] grid place-items-center">
          {/* starfield */}
          {STARS.map((s, i) => (
            <span
              key={i}
              className="iss-anim absolute rounded-full bg-white"
              style={{ left: s.x, top: s.y, width: 2, height: 2, animation: `iss-twinkle ${s.d} ease-in-out infinite` }}
            />
          ))}

          {/* inclined orbit ring + satellite */}
          <div className="absolute inset-0" style={{ transform: "rotate(-20deg)" }}>
            <div className="absolute inset-2 rounded-full border border-dashed border-cyan-300/30" />
            <div className="iss-anim absolute inset-2" style={{ animation: "iss-orbit 9s linear infinite" }}>
              <span
                className="iss-anim absolute left-1/2 -top-[3px] -translate-x-1/2 rounded-full bg-cyan-300"
                style={{ width: 7, height: 7, animation: "iss-pulse 2.2s ease-in-out infinite" }}
              />
            </div>
          </div>

          {/* Earth */}
          <div
            className="relative w-[72px] h-[72px] rounded-full overflow-hidden"
            style={{
              background: "radial-gradient(circle at 34% 30%, #4ea3e0 0%, #1f6fb2 48%, #0b3a66 100%)",
              boxShadow: "0 0 22px 2px rgba(56,135,196,.35), inset -6px -6px 14px rgba(0,0,0,.45)",
            }}
          >
            {/* rotating landmasses */}
            <div
              className="iss-anim absolute inset-[-30%]"
              style={{
                background: [
                  "radial-gradient(circle at 28% 40%, rgba(60,150,70,.85) 0 10%, transparent 11%)",
                  "radial-gradient(circle at 60% 30%, rgba(80,165,85,.8) 0 8%, transparent 9%)",
                  "radial-gradient(circle at 70% 64%, rgba(70,155,78,.8) 0 11%, transparent 12%)",
                  "radial-gradient(circle at 44% 72%, rgba(90,170,95,.7) 0 7%, transparent 8%)",
                  "radial-gradient(circle at 18% 60%, rgba(65,150,72,.7) 0 6%, transparent 7%)",
                ].join(","),
                animation: "iss-spin 26s linear infinite",
              }}
            />
            {/* day/night terminator */}
            <div
              className="absolute inset-0"
              style={{ background: "linear-gradient(115deg, transparent 42%, rgba(0,0,10,.55) 72%)" }}
            />
          </div>
        </div>

        {/* readings */}
        <div className="flex-1 grid grid-cols-2 gap-x-4 gap-y-3 min-w-0">
          <Reading label="Latitude" value={geo(iss.lat, "N", "S")} cls="mono" />
          <Reading label="Longitude" value={geo(iss.lon, "E", "W")} cls="mono" />
          <Reading label="Altitude" value={`${iss.altKm} km`} cls="mono text-cyan-300" />
          <Reading label="Speed" value={`${iss.velKmh.toLocaleString()} km/h`} cls="mono text-cyan-300" />
          <Reading
            label="Sunlight"
            value={iss.visibility ? (sunlit ? "☀ day" : "🌑 night") : "—"}
            cls={sunlit ? "text-amber-300" : "text-sky-300"}
          />
          <Reading label="Orbit" value="~92 min" cls="text-muted" hint="≈16 / day" />
        </div>
      </div>
    </section>
  );
}

function Reading({ label, value, cls, hint }: {
  label: string; value: string; cls?: string; hint?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-muted text-xs">{label}</div>
      <div className={"text-lg font-bold truncate " + (cls || "")}>{value}</div>
      {hint && <div className="text-muted text-[10px] mt-0.5 truncate">{hint}</div>}
    </div>
  );
}
