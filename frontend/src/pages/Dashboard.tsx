import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExploitOut, Profile, StatsBucket, StatsOut, TeamOut, useApi } from "../api/client";
import { Card } from "../components/Card";
import { subscribe, FarmEvent } from "../api/ws";

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

  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [live, setLive] = useState<"open" | "closed" | "error">("closed");
  useEffect(() => {
    let seq = 0;
    return subscribe(
      profile,
      (e) => setFeed((prev) => [{ ...e, at: Date.now(), seq: seq++ }, ...prev].slice(0, 120)),
      setLive,
    );
  }, [profile.url, profile.token]);

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
        <Big title="Duplicate" value={t.duplicate} color="text-purple-300" />
        <Big title="Error" value={t.error} color="text-pink-300" />
      </div>

      <div className="col-span-12">
        <Card title="Flag breakdown">
          <StatusBar b={t} total={total} />
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

      <div className="col-span-12 md:col-span-4">
        <Card title="Fleet">
          <div className="space-y-3">
            <Line label="Exploits" value={`${enabled} on / ${exploits.data?.length ?? 0}`} />
            <Line label="Target teams" value={String(teams.data?.length ?? 0)} />
            <Line label="Accepted / 1m" value={String(s.last_minute.accepted)} cls="text-emerald-400" />
            <Line label="Accepted / 1h" value={String(s.last_hour.accepted)} cls="text-emerald-400" />
          </div>
        </Card>
      </div>
      <div className="col-span-12 md:col-span-8">
        <Card title="Live feed" right={<LiveDot state={live} />}>
          {feed.length === 0 && <div className="text-muted text-sm">waiting for events…</div>}
          <ul className="space-y-1 max-h-[280px] overflow-auto text-xs">
            {feed.map((e) => (
              <li key={e.seq} className="flex items-baseline gap-2">
                <span className="text-muted mono shrink-0">{fmtTime(e.at)}</span>
                <EventLabel kind={e.kind} />
                <span className="text-muted truncate">{describe(e)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

type FeedItem = FarmEvent & { at: number; seq: number };

function rateColor(rate: number): string {
  if (rate >= 80) return "text-emerald-400";
  if (rate >= 50) return "text-yellow-300";
  return "text-red-400";
}

function fmtTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

const EVENT_STYLE: Record<string, string> = {
  submit: "bg-emerald-800 text-emerald-100",
  flags: "bg-blue-800 text-blue-100",
  run: "bg-sky-900 text-sky-100",
  exploit: "bg-indigo-800 text-indigo-100",
  requeue: "bg-yellow-800 text-yellow-100",
  expired: "bg-gray-700 text-gray-200",
  submitter_error: "bg-pink-800 text-pink-100",
};

function EventLabel({ kind }: { kind: string }) {
  const cls = EVENT_STYLE[kind] || "bg-gray-700 text-gray-200";
  return <span className={"px-1.5 py-0.5 rounded mono shrink-0 " + cls}>{kind}</span>;
}

function describe(e: FarmEvent): string {
  const p = e.payload || {};
  switch (e.kind) {
    case "submit":
      return `+${p.accepted} accepted, ${p.rejected} rejected, ${p.retry} retry via ${p.protocol}`;
    case "flags":
      return `${p.new} new` + (p.duplicate ? `, ${p.duplicate} dup` : "") + (p.manual ? " (manual)" : "");
    case "run":
      return `${p.sploit} → ${p.team ?? p.target_ip ?? "?"}: ${p.flags_found} flags (exit ${p.exit_code})`;
    case "exploit":
      return `${p.name}` + (p.host ? ` @ ${p.host}` : "") +
        (p.enabled !== undefined ? ` → ${p.enabled ? "on" : "off"}` : "");
    case "requeue":
      return `${p.flags} flag(s) requeued from ${p.from}`;
    case "expired":
      return `${p.flags} flag(s) expired`;
    case "submitter_error":
      return `jury gave no verdict for ${p.flags} flag(s): ${p.error ?? "?"}`;
    default:
      return JSON.stringify(p);
  }
}

function LiveDot({ state }: { state: "open" | "closed" | "error" }) {
  const map = { open: "bg-emerald-400", closed: "bg-gray-500", error: "bg-red-400" };
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted">
      <span className={"w-2 h-2 rounded-full " + map[state]} />
      {state === "open" ? "live" : state}
    </span>
  );
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

const SEGMENTS: { key: keyof StatsBucket; cls: string; label: string }[] = [
  { key: "accepted", cls: "bg-emerald-500", label: "accepted" },
  { key: "queued", cls: "bg-yellow-400", label: "queued" },
  { key: "rejected", cls: "bg-red-500", label: "rejected" },
  { key: "error", cls: "bg-pink-500", label: "error" },
  { key: "duplicate", cls: "bg-purple-500", label: "duplicate" },
  { key: "expired", cls: "bg-gray-500", label: "expired" },
];

function StatusBar({ b, total }: { b: StatsBucket; total: number }) {
  if (total === 0) {
    return <div className="text-muted text-sm">no flags yet</div>;
  }
  return (
    <div className="space-y-3">
      <div className="flex h-3 rounded-full overflow-hidden bg-panel2">
        {SEGMENTS.map((seg) => {
          const v = b[seg.key] as number;
          if (!v) return null;
          return (
            <div key={seg.key} className={seg.cls} style={{ width: `${(v / total) * 100}%` }}
                 title={`${seg.label}: ${v}`} />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SEGMENTS.map((seg) => (
          <span key={seg.key} className="flex items-center gap-1.5 text-muted">
            <span className={"w-2.5 h-2.5 rounded-sm " + seg.cls} />
            {seg.label} <span className="mono text-white">{b[seg.key] as number}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function BucketRow({ b }: { b: StatsBucket }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 text-sm">
      <Stat label="accepted" value={b.accepted} cls="text-emerald-400" />
      <Stat label="rejected" value={b.rejected} cls="text-red-400" />
      <Stat label="queued" value={b.queued} cls="text-yellow-300" />
      <Stat label="expired" value={b.expired} cls="text-gray-300" />
      <Stat label="duplicate" value={b.duplicate} cls="text-purple-300" />
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
      <table className="w-full text-sm">
        <thead className="text-muted">
          <tr>
            <th className="text-left font-medium pb-2">{keyLabel}</th>
            <th className="text-right font-medium pb-2">accepted</th>
            <th className="text-right font-medium pb-2">rejected</th>
            <th className="text-right font-medium pb-2">queued</th>
          </tr>
        </thead>
        <tbody>
          {filtered.slice(0, 15).map((r) => (
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
  );
}
