import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { buildApi, Profile, StatsBucket, StatsOut } from "../api/client";
import { Card } from "../components/Card";
import { subscribe, FarmEvent } from "../api/ws";

export function Dashboard({ profile }: { profile: Profile }) {
  const api = buildApi(profile);
  const stats = useQuery({
    queryKey: ["stats", profile.url],
    queryFn: async () => (await api.get<StatsOut>("/api/stats")).data,
    refetchInterval: 4_000,
  });

  const [feed, setFeed] = useState<FarmEvent[]>([]);
  useEffect(() => {
    return subscribe(profile, (e) => {
      setFeed((prev) => [e, ...prev].slice(0, 100));
    });
  }, [profile.url, profile.token]);

  if (!stats.data) {
    return <div className="text-muted">loading…</div>;
  }
  const s = stats.data;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Big title="Accepted" value={s.totals.accepted} color="text-emerald-400" />
        <Big title="Queued" value={s.totals.queued} color="text-yellow-300" />
        <Big title="Rejected" value={s.totals.rejected} color="text-red-400" />
        <Big title="Expired" value={s.totals.expired} color="text-gray-300" />
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
        <Card title="By exploit">
          <BucketTable rows={s.by_sploit} keyLabel="Sploit" />
        </Card>
      </div>
      <div className="col-span-12 md:col-span-6">
        <Card title="By team">
          <BucketTable rows={s.by_team} keyLabel="Team" />
        </Card>
      </div>

      <div className="col-span-12">
        <Card title="Live feed">
          {feed.length === 0 && <div className="text-muted text-sm">waiting for events…</div>}
          <ul className="space-y-1 max-h-[260px] overflow-auto mono text-xs">
            {feed.map((e, i) => (
              <li key={i}>
                <span className="text-emerald-400">{e.kind}</span>{" "}
                <span className="text-muted">{JSON.stringify(e.payload)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function Big({ title, value, color }: { title: string; value: number; color: string }) {
  return (
    <div className="bg-panel border border-border rounded-xl p-4">
      <div className="text-muted text-sm">{title}</div>
      <div className={"text-3xl font-bold mono " + color}>{value}</div>
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
  if (rows.length === 0) {
    return <div className="text-muted text-sm">no data yet</div>;
  }
  return (
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
        {rows.slice(0, 12).map((r) => (
          <tr key={r.label} className="border-t border-border">
            <td className="py-1 mono">{r.label}</td>
            <td className="py-1 mono text-right text-emerald-400">{r.accepted}</td>
            <td className="py-1 mono text-right text-red-400">{r.rejected}</td>
            <td className="py-1 mono text-right text-yellow-300">{r.queued}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
