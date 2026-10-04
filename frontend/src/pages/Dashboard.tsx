import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExploitOut, Profile, StatsBucket, StatsOut, TeamOut, useApi } from "../api/client";
import { Card } from "../components/Card";
import { C, Donut } from "../components/charts";
import { IssTracker } from "../components/IssTracker";
import { SortHeader, useSort } from "../components/sortable";

export function Dashboard({ profile }: { profile: Profile }) {
  const api = useApi(profile);
  const stats = useQuery({
    queryKey: ["stats", profile.url],
    queryFn: async () => (await api.get<StatsOut>("/api/stats")).data,
    refetchInterval: 4_000,
  });
  const exploits = useQuery({
    queryKey: ["exploits", profile.url],
    queryFn: async () => (await api.get<ExploitOut[]>("/api/exploits")).data,
    refetchInterval: 10_000,
  });
  const teams = useQuery({
    queryKey: ["teams", profile.url],
    queryFn: async () => (await api.get<TeamOut[]>("/api/teams")).data,
    refetchInterval: 30_000,
  });

  if (!stats.data) {
    return <div className="text-muted">loading…</div>;
  }
  const s = stats.data;
  const t = s.totals;
  const total = t.accepted + t.rejected + t.queued + t.expired + t.duplicate + t.error;
  const verdicts = t.accepted + t.rejected;
  const acceptRate = verdicts ? Math.round((t.accepted / verdicts) * 100) : 0;
  const enabled = exploits.data?.filter((e) => e.enabled).length ?? 0;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Big title="Total" value={total} />
        <Big title="Accept rate" value={`${acceptRate}%`} color={rateColor(acceptRate)}
             hint={`${t.accepted} of ${verdicts} verdicts`} />
        <Big title="Accepted" value={t.accepted} color="text-emerald-400" />
        <Big title="Queued" value={t.queued} color="text-yellow-300" />
        <Big title="Rejected" value={t.rejected} color="text-red-400" />
        <Big title="Expired" value={t.expired} color="text-gray-300" />
        <Big title="Deduplicated" value={s.deduplicated} color="text-purple-300"
             hint="repeats dropped at ingest" />
        <Big title="Error" value={t.error} color="text-pink-300" />
      </div>

      <div className="col-span-12 md:col-span-5">
        <Card title="Flag breakdown" className="h-full">
          <FlagDonut b={t} total={total} />
        </Card>
      </div>
      <div className="col-span-12 sm:col-span-6 md:col-span-4">
        <IssTracker />
      </div>
      <div className="col-span-12 sm:col-span-6 md:col-span-3">
        <Card title="Fleet" className="h-full">
          <div className="space-y-3">
            <Line label="Exploits" value={`${enabled} on / ${exploits.data?.length ?? 0}`} />
            <Line label="Target teams" value={String(teams.data?.length ?? 0)} />
            <Line label="Accepted / 1m" value={String(s.last_minute.accepted)} cls="text-emerald-400" />
            <Line label="Accepted / 1h" value={String(s.last_hour.accepted)} cls="text-emerald-400" />
          </div>
        </Card>
      </div>

      <div className="col-span-12 md:col-span-6">
        <Card title="Last minute">
          <BucketRow b={s.last_minute} />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="Last hour">
          <BucketRow b={s.last_hour} />
        </Card>
      </div>

      <div className="col-span-12 md:col-span-6">
        <Card title="By exploit" right={<span className="text-xs text-muted">{s.by_sploit.length}</span>}>
          <BucketTable rows={s.by_sploit} keyLabel="Sploit" />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="By team" right={<span className="text-xs text-muted">{s.by_team.length}</span>}>
          <BucketTable rows={s.by_team} keyLabel="Team" />
        </Card>
      </div>

    </div>
  );
}

function rateColor(rate: number): string {
  if (rate >= 80) return "text-emerald-400";
  if (rate >= 50) return "text-yellow-300";
  return "text-red-400";
}

function Big({ title, value, color, hint }: {
  title: string; value: number | string; color?: string; hint?: string;
}) {
  return (
    <div className="bg-panel border border-border rounded-xl p-4">
      <div className="text-muted text-sm">{title}</div>
      <div className={"text-3xl font-bold mono " + (color || "")}>{value}</div>
      {hint && <div className="text-muted text-xs mt-1 truncate">{hint}</div>}
    </div>
  );
}

function Line({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-muted text-sm">{label}</span>
      <span className={"font-bold mono " + (cls || "")}>{value}</span>
    </div>
  );
}

// Fixed status order; expired (grey) sits between rejected (red) and error
// (pink) so the two warm hues are never adjacent arcs. Colours match the rest
// of the UI and carry a labelled, valued legend — never colour alone.
const STATUS_SEGMENTS: { key: keyof StatsBucket; label: string; color: string }[] = [
  { key: "accepted", label: "accepted", color: C.accepted },
  { key: "queued", label: "queued", color: C.queued },
  { key: "rejected", label: "rejected", color: C.rejected },
  { key: "expired", label: "expired", color: C.expired },
  { key: "error", label: "error", color: C.error },
];

function FlagDonut({ b, total }: { b: StatsBucket; total: number }) {
  const [active, setActive] = useState<string | null>(null);
  if (total === 0) {
    return <div className="text-muted text-sm">no flags yet</div>;
  }
  const segs = STATUS_SEGMENTS.map((s) => ({
    label: s.label, value: b[s.key] as number, color: s.color,
  }));
  return (
    <div className="flex items-center gap-5 h-full">
      <Donut segments={segs} total={total} active={active} onActive={setActive} />
      <div className="flex-1 space-y-1.5 min-w-0">
        {segs.map((s) => {
          const pct = Math.round((s.value / total) * 100);
          const dim = active !== null && active !== s.label;
          return (
            <div
              key={s.label}
              onMouseEnter={() => setActive(s.label)}
              onMouseLeave={() => setActive(null)}
              className={"flex items-center gap-2 text-sm transition-opacity " + (dim ? "opacity-40" : "")}
            >
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: s.color }} />
              <span className="text-muted flex-1 truncate">{s.label}</span>
              <span className="mono text-white">{s.value.toLocaleString()}</span>
              <span className="mono text-muted text-xs w-9 text-right">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BucketRow({ b }: { b: StatsBucket }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 text-sm">
      <Stat label="accepted" value={b.accepted} cls="text-emerald-400" />
      <Stat label="rejected" value={b.rejected} cls="text-red-400" />
      <Stat label="queued" value={b.queued} cls="text-yellow-300" />
      <Stat label="expired" value={b.expired} cls="text-gray-300" />
      <Stat label="error" value={b.error} cls="text-pink-300" />
    </div>
  );
}

function Stat({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div>
      <div className="text-muted text-xs">{label}</div>
      <div className={"font-bold mono " + cls}>{value}</div>
    </div>
  );
}

function BucketTable({ rows, keyLabel }: { rows: StatsBucket[]; keyLabel: string }) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const filtered = useMemo(
    () => (needle ? rows.filter((r) => r.label.toLowerCase().includes(needle)) : rows),
    [rows, needle],
  );
  const { sorted, sort } = useSort<StatsBucket>(
    filtered,
    {
      label: (r) => r.label,
      accepted: (r) => r.accepted,
      rejected: (r) => r.rejected,
      queued: (r) => r.queued,
    },
    { key: "accepted", dir: "desc" },
  );
  if (rows.length === 0) {
    return <div className="text-muted text-sm">no data yet</div>;
  }
  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`filter ${keyLabel.toLowerCase()}…`}
        className="w-full bg-panel2 border border-border rounded px-2 py-1 mb-2 text-xs"
      />
      {/* Every row did something (it has flags); show them all, scrolling. */}
      <div className="max-h-[340px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-muted sticky top-0 bg-panel">
            <tr>
              <SortHeader label={keyLabel} sortKey="label" sort={sort} className="pb-2" />
              <SortHeader label="accepted" sortKey="accepted" sort={sort} align="right" className="pb-2" />
              <SortHeader label="rejected" sortKey="rejected" sort={sort} align="right" className="pb-2" />
              <SortHeader label="queued" sortKey="queued" sort={sort} align="right" className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.label} className="border-t border-border">
                <td className="py-1 mono">{r.label}</td>
                <td className="py-1 mono text-right text-emerald-400">{r.accepted}</td>
                <td className="py-1 mono text-right text-red-400">{r.rejected}</td>
                <td className="py-1 mono text-right text-yellow-300">{r.queued}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={4} className="py-2 text-muted text-xs">no match</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
