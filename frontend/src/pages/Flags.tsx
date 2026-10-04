import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlagOut, Profile, useApi } from "../api/client";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import { SearchBar, countLabel } from "../components/SearchBar";
import { highlight } from "../components/highlight";

const STATUSES = ["", "QUEUED", "PENDING", "ACCEPTED", "REJECTED", "EXPIRED", "DUPLICATE", "ERROR"];
// Statuses the bulk "requeue matching" action accepts (see POST /api/flags/requeue).
const REQUEUEABLE = new Set(["REJECTED", "ERROR", "EXPIRED"]);
const PAGE = 300;

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export function Flags({ profile }: { profile: Profile }) {
  const api = useApi(profile);
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  // Debounce the text input so typing doesn't fire one request per keystroke.
  const searchQuery = useDebounced(search.trim(), 300);
  const needle = searchQuery.toLowerCase();
  const [notice, setNotice] = useState<string | null>(null);
  // Flag ids whose (possibly long) jury response is expanded in full.
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggleResponse = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const flags = useQuery({
    queryKey: ["flags", profile.url, status, searchQuery],
    queryFn: async () => {
      const params: Record<string, string> = { limit: String(PAGE) };
      if (status) params.status = status;
      if (searchQuery) params.q = searchQuery;
      const res = await api.get<FlagOut[]>("/api/flags", { params });
      const total = Number(res.headers["x-total-count"] ?? res.data.length);
      return { rows: res.data, total };
    },
    refetchInterval: 5_000,
  });

  const requeueMatching = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ requeued: number }>("/api/flags/requeue", {
          status,
          q: searchQuery || null,
        })
      ).data,
    onSuccess: (data) => {
      setNotice(`requeued ${data.requeued} flag(s)`);
      setTimeout(() => setNotice(null), 3000);
      qc.invalidateQueries({ queryKey: ["flags"] });
    },
    onError: (e: any) => setNotice(e?.response?.data?.detail || e.message),
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
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder="Search flags — flag, sploit, team, IP, response (partial, case-insensitive)"
        />
      </div>

      <div className="col-span-12">
        <Card
          title="Flags"
          right={
            <div className="flex gap-2 text-xs items-center">
              {notice && <span className="text-emerald-400">{notice}</span>}
              {flags.data && (
                <span className="text-muted mono">
                  {countLabel(flags.data.rows.length, flags.data.total, flags.data.rows.length < flags.data.total)}
                </span>
              )}
              {REQUEUEABLE.has(status) && (
                <button
                  onClick={() => {
                    if (confirm(`Requeue every ${status} flag matching the search (still within flag_lifetime)?`)) {
                      requeueMatching.mutate();
                    }
                  }}
                  disabled={requeueMatching.isPending}
                  className="px-2 py-1 rounded border border-border hover:bg-panel2 disabled:opacity-50"
                  title="Send these flags to the jury again — e.g. after fixing the jury token"
                >
                  requeue matching
                </button>
              )}
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
                {flags.data?.rows.map((f) => (
                  <tr key={f.id} className="border-t border-border align-top">
                    <td className="py-1 mono">{highlight(f.flag, needle)}</td>
                    <td className="py-1"><StatusPill status={f.status} /></td>
                    <td className="py-1 mono text-muted">{highlight(f.sploit, needle)}</td>
                    <td className="py-1 mono text-muted">{highlight(f.team || f.target_ip, needle)}</td>
                    <td className="py-1 mono text-xs text-muted">
                      {new Date(f.captured_at).toLocaleTimeString()}
                    </td>
                    <td className="py-1 text-xs text-muted max-w-[320px]">
                      {f.response ? (
                        <button
                          onClick={() => toggleResponse(f.id)}
                          title={expanded.has(f.id) ? "click to collapse" : f.response}
                          className={
                            "text-left w-full cursor-pointer hover:text-white " +
                            (expanded.has(f.id) ? "whitespace-pre-wrap break-all" : "truncate")
                          }
                        >
                          {highlight(f.response, needle)}
                        </button>
                      ) : (
                        <span className="text-muted">-</span>
                      )}
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
                {flags.data && flags.data.rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-muted text-center py-6">
                      {searchQuery || status ? "no flags match" : "no flags"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
