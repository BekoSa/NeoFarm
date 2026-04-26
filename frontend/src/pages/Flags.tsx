import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { buildApi, FlagOut, Profile } from "../api/client";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";

const STATUSES = ["", "QUEUED", "PENDING", "ACCEPTED", "REJECTED", "EXPIRED", "DUPLICATE", "ERROR"];

export function Flags({ profile }: { profile: Profile }) {
  const api = buildApi(profile);
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [sploit, setSploit] = useState("");
  const [team, setTeam] = useState("");

  const flags = useQuery({
    queryKey: ["flags", profile.url, status, sploit, team],
    queryFn: async () => {
      const params: Record<string, string> = { limit: "300" };
      if (status) params.status = status;
      if (sploit) params.sploit = sploit;
      if (team) params.team = team;
      return (await api.get<FlagOut[]>("/api/flags", { params })).data;
    },
    refetchInterval: 5_000,
  });

  const requeue = useMutation({
    mutationFn: async (id: number) => api.post(`/api/flags/${id}/requeue`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flags"] }),
  });
  const del = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/flags/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flags"] }),
  });

  return (
    <Card
      title="Flags"
      right={
        <div className="flex gap-2 text-xs">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="bg-panel2 border border-border rounded px-2 py-1"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "any status"}
              </option>
            ))}
          </select>
          <input
            placeholder="sploit"
            value={sploit}
            onChange={(e) => setSploit(e.target.value)}
            className="bg-panel2 border border-border rounded px-2 py-1 mono w-32"
          />
          <input
            placeholder="team"
            value={team}
            onChange={(e) => setTeam(e.target.value)}
            className="bg-panel2 border border-border rounded px-2 py-1 mono w-28"
          />
        </div>
      }
    >
      <div className="overflow-auto max-h-[68vh]">
        <table className="w-full text-sm">
          <thead className="text-muted sticky top-0 bg-panel">
            <tr>
              <th className="text-left font-medium py-1">flag</th>
              <th className="text-left font-medium py-1">status</th>
              <th className="text-left font-medium py-1">sploit</th>
              <th className="text-left font-medium py-1">team</th>
              <th className="text-left font-medium py-1">captured</th>
              <th className="text-left font-medium py-1">response</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {flags.data?.map((f) => (
              <tr key={f.id} className="border-t border-border align-top">
                <td className="py-1 mono">{f.flag}</td>
                <td className="py-1"><StatusPill status={f.status} /></td>
                <td className="py-1 mono text-muted">{f.sploit}</td>
                <td className="py-1 mono text-muted">{f.team || f.target_ip}</td>
                <td className="py-1 mono text-xs text-muted">
                  {new Date(f.captured_at).toLocaleTimeString()}
                </td>
                <td className="py-1 text-xs text-muted truncate max-w-[300px]">
                  {f.response}
                </td>
                <td className="py-1 text-right whitespace-nowrap">
                  <button
                    onClick={() => requeue.mutate(f.id)}
                    className="text-xs px-2 py-0.5 rounded border border-border hover:bg-panel2 mr-1"
                  >
                    requeue
                  </button>
                  <button
                    onClick={() => del.mutate(f.id)}
                    className="text-xs px-2 py-0.5 rounded border border-border hover:bg-red-900"
                  >
                    delete
                  </button>
                </td>
              </tr>
            ))}
            {flags.data && flags.data.length === 0 && (
              <tr>
                <td colSpan={7} className="text-muted text-center py-6">
                  no flags
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
