import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NodeOut, NodeTaskOut, Profile, useApi } from "../api/client";
import { Card } from "../components/Card";
import { SearchBar, countLabel } from "../components/SearchBar";
import { highlight } from "../components/highlight";
import { SortHeader, useSort } from "../components/sortable";

/** A node is "online" if we heard from it within a few heartbeat intervals. */
const ONLINE_MS = 20_000;

function isOnline(n: NodeOut): boolean {
  return !!n.last_seen && Date.now() - Date.parse(n.last_seen) < ONLINE_MS;
}

function matches(needle: string, ...fields: (string | null | undefined)[]): boolean {
  if (!needle) return true;
  return fields.some((f) => (f ?? "").toLowerCase().includes(needle));
}

export function Nodes({ profile }: { profile: Profile }) {
  const api = useApi(profile);
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const needle = query.trim().toLowerCase();

  const nodes = useQuery({
    queryKey: ["nodes", profile.url],
    queryFn: async () => (await api.get<NodeOut[]>("/api/nodes")).data,
    refetchInterval: 5_000,
    retry: false,
  });

  // Old server without the nodes API yet (needs a restart to pick it up).
  const notDeployed = (nodes.error as any)?.response?.status === 404;

  const shown = useMemo(
    () => (nodes.data ?? []).filter((n) => matches(needle, n.name, n.hostname, n.ip, n.labels)),
    [nodes.data, needle],
  );
  const sorted = useSort<NodeOut>(
    shown,
    {
      name: (n) => n.name ?? n.hostname ?? "",
      status: (n) => (isOnline(n) ? 1 : 0),
      host: (n) => n.hostname ?? "",
      tasks: (n) => n.task_count,
      running: (n) => n.running.length,
      last_seen: (n) => (n.last_seen ? Date.parse(n.last_seen) : 0),
    },
    { key: "status", dir: "desc" },
  );

  const toggle = useMutation({
    mutationFn: async (n: NodeOut) => api.patch(`/api/nodes/${n.id}`, { enabled: !n.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["nodes"] }),
  });
  const del = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/nodes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["nodes"] }),
  });

  const online = (nodes.data ?? []).filter(isOnline).length;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 flex items-center gap-3">
        <div className="flex-1">
          <SearchBar
            value={query}
            onChange={setQuery}
            placeholder="Search nodes — name, host, IP, labels (partial, case-insensitive)"
          />
        </div>
        <span className="text-xs text-muted shrink-0">
          <span className="text-emerald-400 mono">{online}</span> online ·{" "}
          <span className="mono">{nodes.data?.length ?? 0}</span> total
        </span>
      </div>

      {notDeployed && (
        <div className="col-span-12 bg-yellow-950 border border-yellow-800 text-yellow-100 rounded-xl px-4 py-3 text-sm">
          The nodes API isn't live on this server yet. Restart the server
          (<code className="mono">docker compose up -d server</code>) to create the
          table and load it — the running submitter keeps going.
        </div>
      )}

      <div className="col-span-12">
        <Card
          title="Nodes"
          right={<span className="text-xs text-muted">{countLabel(shown.length, nodes.data?.length, !!needle)}</span>}
        >
          {!nodes.data?.length ? (
            <div className="text-muted text-sm">
              {notDeployed
                ? "Waiting for the nodes API…"
                : (
                  <>
                    No nodes yet — run <code className="mono">farm-cli node</code> on a
                    teammate's machine, then push exploits to it here.
                  </>
                )}
            </div>
          ) : shown.length === 0 ? (
            <div className="text-muted text-sm">No node matches “{query}”.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-muted">
                <tr>
                  <SortHeader label="status" sortKey="status" sort={sorted.sort} className="pb-1" />
                  <SortHeader label="name" sortKey="name" sort={sorted.sort} className="pb-1" />
                  <SortHeader label="host / ip" sortKey="host" sort={sorted.sort} className="pb-1" />
                  <th className="pb-1 text-left font-normal">labels</th>
                  <SortHeader label="running" sortKey="running" sort={sorted.sort} align="right" className="pb-1" />
                  <SortHeader label="tasks" sortKey="tasks" sort={sorted.sort} align="right" className="pb-1" />
                  <SortHeader label="last seen" sortKey="last_seen" sort={sorted.sort} className="pb-1" />
                  <th className="pb-1" />
                  <th className="pb-1" />
                </tr>
              </thead>
              <tbody>
                {sorted.sorted.map((n) => (
                  <Fragment key={n.id}>
                    <tr className="border-t border-border align-top">
                      <td className="py-1.5">
                        <span className="flex items-center gap-1.5 text-xs">
                          <span className={"w-2 h-2 rounded-full " + (isOnline(n) ? "bg-emerald-400" : "bg-gray-500")} />
                          {isOnline(n) ? "online" : "offline"}
                        </span>
                      </td>
                      <td className="py-1.5 mono">{highlight(n.name ?? n.hostname ?? "?", needle)}</td>
                      <td className="py-1.5 mono text-muted text-xs">
                        {highlight(n.hostname ?? "-", needle)}
                        {n.ip ? <span className="text-gray-500"> · {highlight(n.ip, needle)}</span> : null}
                      </td>
                      <td className="py-1.5 text-xs">
                        {n.labels
                          ? n.labels.split(",").map((l) => (
                              <span key={l} className="mr-1 px-1.5 py-0.5 rounded bg-panel2 text-muted mono">
                                {l.trim()}
                              </span>
                            ))
                          : <span className="text-gray-600">-</span>}
                      </td>
                      <td className="py-1.5 text-right mono">
                        {n.running.length
                          ? <span className="text-sky-400" title={n.running.map((r) => r.sploit).join(", ")}>{n.running.length}</span>
                          : <span className="text-gray-600">0</span>}
                      </td>
                      <td className="py-1.5 text-right mono text-muted">{n.task_count}</td>
                      <td className="py-1.5 text-xs text-muted">
                        {n.last_seen ? new Date(n.last_seen).toLocaleTimeString() : "-"}
                        {n.agent_version ? <span className="text-gray-600"> · v{n.agent_version}</span> : null}
                      </td>
                      <td className="py-1.5">
                        <button
                          onClick={() => toggle.mutate(n)}
                          className={"text-xs px-2 py-0.5 rounded " + (n.enabled ? "bg-emerald-700" : "bg-gray-700")}
                          title={n.enabled ? "Stop all tasks on this node" : "Let this node run tasks"}
                        >
                          {n.enabled ? "on" : "off"}
                        </button>
                      </td>
                      <td className="py-1.5 text-right whitespace-nowrap">
                        <button
                          onClick={() => setOpen(open === n.id ? null : n.id)}
                          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-panel2 mr-1"
                        >
                          {open === n.id ? "hide" : "tasks"}
                        </button>
                        <button
                          onClick={() => del.mutate(n.id)}
                          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-red-900"
                        >
                          del
                        </button>
                      </td>
                    </tr>
                    {open === n.id && (
                      <tr className="border-t border-border/40 bg-panel2/40">
                        <td colSpan={9} className="p-3">
                          <TaskManager profile={profile} node={n} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}

function TaskManager({ profile, node }: { profile: Profile; node: NodeOut }) {
  const api = useApi(profile);
  const qc = useQueryClient();
  const tasks = useQuery({
    queryKey: ["node-tasks", profile.url, node.id],
    queryFn: async () => (await api.get<NodeTaskOut[]>(`/api/nodes/${node.id}/tasks`)).data,
    refetchInterval: 5_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["node-tasks", profile.url, node.id] });
    qc.invalidateQueries({ queryKey: ["nodes"] });
  };

  const toggle = useMutation({
    mutationFn: async (t: NodeTaskOut) =>
      api.patch(`/api/nodes/${node.id}/tasks/${t.id}`, { enabled: !t.enabled }),
    onSuccess: invalidate,
  });
  const del = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/nodes/${node.id}/tasks/${id}`),
    onSuccess: invalidate,
  });

  const running = useMemo(() => new Set(node.running.map((r) => r.sploit)), [node.running]);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-6">
        <div className="text-xs text-muted mb-2 font-semibold">Assigned exploits</div>
        {tasks.data?.length ? (
          <table className="w-full text-xs">
            <thead className="text-muted">
              <tr>
                <th className="text-left font-normal pb-1">sploit</th>
                <th className="text-left font-normal pb-1">file</th>
                <th className="text-left font-normal pb-1">args</th>
                <th className="text-left font-normal pb-1">state</th>
                <th />
                <th />
              </tr>
            </thead>
            <tbody>
              {tasks.data.map((t) => (
                <tr key={t.id} className="border-t border-border/50">
                  <td className="py-1 mono">
                    {t.sploit}
                    {running.has(t.sploit) && (
                      <span className="ml-1.5 text-sky-400" title="running now">●</span>
                    )}
                  </td>
                  <td className="py-1 mono text-muted">{t.script_name}</td>
                  <td className="py-1 mono text-muted">{t.args || "-"}</td>
                  <td className="py-1 text-gray-500">rev {t.rev}</td>
                  <td className="py-1">
                    <button
                      onClick={() => toggle.mutate(t)}
                      className={"px-2 py-0.5 rounded " + (t.enabled ? "bg-emerald-700" : "bg-gray-700")}
                    >
                      {t.enabled ? "on" : "off"}
                    </button>
                  </td>
                  <td className="py-1 text-right">
                    <button
                      onClick={() => del.mutate(t.id)}
                      className="px-2 py-0.5 rounded border border-border hover:bg-red-900"
                    >
                      del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted text-xs">No exploits pushed to this node yet.</div>
        )}
      </div>
      <div className="col-span-12 lg:col-span-6">
        <AddTask profile={profile} node={node} onAdded={invalidate} />
      </div>
    </div>
  );
}

function AddTask({
  profile, node, onAdded,
}: {
  profile: Profile;
  node: NodeOut;
  onAdded: () => void;
}) {
  const api = useApi(profile);
  const [sploit, setSploit] = useState("");
  const [args, setArgs] = useState("");
  const [script, setScript] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () =>
      api.post(`/api/nodes/${node.id}/tasks`, {
        sploit: sploit.trim(),
        script,
        args: args.trim() || null,
        enabled: true,
      }),
    onSuccess: () => {
      setSploit("");
      setArgs("");
      setScript("");
      setErr(null);
      onAdded();
    },
    onError: (e: any) => setErr(e?.response?.data?.detail || e?.message || "failed"),
  });

  const ready = sploit.trim().length > 0 && script.length > 0;

  return (
    <div>
      <div className="text-xs text-muted mb-2 font-semibold">Push an exploit</div>
      <div className="flex gap-2 mb-2">
        <input
          value={sploit}
          onChange={(e) => setSploit(e.target.value)}
          placeholder="exploit name"
          className="flex-1 bg-panel2 border border-border rounded px-2 py-1 mono text-xs"
        />
        <input
          value={args}
          onChange={(e) => setArgs(e.target.value)}
          placeholder="extra args (optional)"
          className="flex-1 bg-panel2 border border-border rounded px-2 py-1 mono text-xs"
        />
      </div>
      <textarea
        value={script}
        onChange={(e) => setScript(e.target.value)}
        placeholder={"#!/usr/bin/env python3\n# receives target IP as argv[1]; print flags to stdout"}
        spellCheck={false}
        className="w-full h-40 bg-panel2 border border-border rounded px-2 py-1 mono text-xs resize-y"
      />
      {err && <div className="text-red-400 text-xs mt-1">{err}</div>}
      <div className="flex items-center gap-2 mt-2">
        <button
          disabled={!ready || create.isPending}
          onClick={() => create.mutate()}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-xs px-3 py-1 rounded font-medium"
        >
          {create.isPending ? "pushing…" : "Push to node"}
        </button>
        <span className="text-xs text-muted">
          runs as <code className="mono">script {"<team-ip>"} {args || ""}</code> each round
        </span>
      </div>
    </div>
  );
}
