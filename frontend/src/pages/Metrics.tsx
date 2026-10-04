import { useEffect, useMemo, useState } from "react";
import { Profile, StatsOut, useApi } from "../api/client";
import { Card } from "../components/Card";
import { BarList, C, LineChart } from "../components/charts";

interface Sample {
  t: number;
  accepted: number;
  rejected: number;
  queued: number;
  dedup: number;
  rate: number;
}

// Keep history across tab switches within a session (per server).
const BUF = new Map<string, Sample[]>();
const CAP = 90; // ~6 min at 4s

export function Metrics({ profile }: { profile: Profile }) {
  const api = useApi(profile);
  const [samples, setSamples] = useState<Sample[]>(() => BUF.get(profile.url) ?? []);
  const [stats, setStats] = useState<StatsOut | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = (await api.get<StatsOut>("/api/stats")).data;
        const t = s.totals;
        const verdicts = t.accepted + t.rejected;
        const sample: Sample = {
          t: Date.now(),
          accepted: t.accepted,
          rejected: t.rejected,
          queued: t.queued,
          dedup: s.deduplicated,
          rate: verdicts ? Math.round((t.accepted / verdicts) * 100) : 0,
        };
        const next = [...(BUF.get(profile.url) ?? []), sample].slice(-CAP);
        BUF.set(profile.url, next);
        if (alive) {
          setSamples(next);
          setStats(s);
        }
      } catch {
        /* transient; keep last */
      }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [profile.url, profile.token]);

  // Per-interval deltas (cumulative counters -> throughput).
  const deltas = useMemo(() => {
    const d = { accepted: [] as number[], rejected: [] as number[], dedup: [] as number[], queued: [] as number[], rate: [] as number[] };
    for (let i = 1; i < samples.length; i++) {
      const a = samples[i - 1], b = samples[i];
      d.accepted.push(Math.max(0, b.accepted - a.accepted));
      d.rejected.push(Math.max(0, b.rejected - a.rejected));
      d.dedup.push(Math.max(0, b.dedup - a.dedup));
      d.queued.push(b.queued);
      d.rate.push(b.rate);
    }
    return d;
  }, [samples]);

  const topSploits = useMemo(
    () => rank(stats?.by_sploit), [stats],
  );
  const topTeams = useMemo(
    () => rank(stats?.by_team), [stats],
  );

  const cur = stats?.totals;
  const dedupPerMin = sumLastWindow(samples, (s) => s.dedup, 60_000);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile title="Accept rate" value={cur ? `${rate(cur.accepted, cur.rejected)}%` : "—"} color={C.accepted} />
        <Tile title="Accepted / 1m" value={stats ? String(stats.last_minute.accepted) : "—"} color={C.accepted} />
        <Tile title="Dedup / ~1m" value={String(dedupPerMin)} color={C.dedup} />
        <Tile title="Queued now" value={cur ? String(cur.queued) : "—"} color={C.queued} />
      </div>

      <div className="col-span-12 md:col-span-6">
        <Card title="Submission throughput (per 4s)">
          <LineChart
            series={[
              { label: "accepted", color: C.accepted, values: deltas.accepted },
              { label: "rejected", color: C.rejected, values: deltas.rejected, dashed: true },
            ]}
          />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="Queue depth">
          <LineChart series={[{ label: "queued", color: C.queued, values: deltas.queued }]} />
        </Card>
      </div>

      <div className="col-span-12 md:col-span-6">
        <Card title="Deduplicated (per 4s)">
          <LineChart series={[{ label: "dedup", color: C.dedup, values: deltas.dedup }]} />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="Accept rate over time">
          <LineChart series={[{ label: "accept rate", color: C.accepted, values: deltas.rate }]} unit="%" />
        </Card>
      </div>

      <div className="col-span-12 md:col-span-6">
        <Card title="Top exploits by accepted">
          <BarList rows={topSploits} color={C.accepted} empty="no data yet" />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="Top teams by accepted">
          <BarList rows={topTeams} color={C.accepted} empty="no data yet" />
        </Card>
      </div>
    </div>
  );
}

function rank(buckets: StatsOut["by_sploit"] | undefined) {
  return (buckets ?? [])
    .map((b) => ({ label: b.label, value: b.accepted }))
    .filter((r) => r.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
}

function rate(a: number, r: number): number {
  return a + r ? Math.round((a / (a + r)) * 100) : 0;
}

/** Sum of a cumulative counter's increase over the last `windowMs`. */
function sumLastWindow(samples: Sample[], get: (s: Sample) => number, windowMs: number): number {
  if (samples.length < 2) return 0;
  const cutoff = Date.now() - windowMs;
  const recent = samples.filter((s) => s.t >= cutoff);
  if (recent.length < 2) return 0;
  return Math.max(0, get(recent[recent.length - 1]) - get(recent[0]));
}

function Tile({ title, value, color }: { title: string; value: string; color: string }) {
  return (
    <div className="bg-panel border border-border rounded-xl p-4">
      <div className="text-muted text-sm">{title}</div>
      <div className="text-2xl font-bold mono" style={{ color }}>{value}</div>
    </div>
  );
}
