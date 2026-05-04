import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FarmConfig, Profile, useApi } from "../api/client";
import { Card } from "../components/Card";

export function Config({ profile }: { profile: Profile }) {
  const api = useApi(profile);
  const qc = useQueryClient();
  const cfg = useQuery({
    queryKey: ["config", profile.url],
    queryFn: async () => (await api.get<FarmConfig>("/api/config")).data,
  });
  const protocols = useQuery({
    queryKey: ["protocols", profile.url],
    queryFn: async () => (await api.get<string[]>("/api/config/protocols")).data,
  });

  const [text, setText] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (cfg.data && !text) {
      setText(JSON.stringify(cfg.data, null, 2));
    }
  }, [cfg.data, text]);

  const save = useMutation({
    mutationFn: async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch (e: any) {
        throw new Error("invalid JSON: " + e.message);
      }
      return (await api.put("/api/config", parsed)).data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setErr(null);
      setOk(true);
      setTimeout(() => setOk(false), 2000);
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.detail || e.message);
      setOk(false);
    },
  });

  if (!cfg.data) return <div className="text-muted">loading config…</div>;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-8">
        <Card
          title="config.yml (live)"
          right={
            <div className="flex gap-2 items-center text-xs">
              {ok && <span className="text-emerald-400">saved</span>}
              {err && <span className="text-red-400">{err}</span>}
              <button
                onClick={() => save.mutate()}
                disabled={save.isPending}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-3 py-1.5 rounded text-white"
              >
                {save.isPending ? "saving…" : "save & reload"}
              </button>
            </div>
          }
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={28}
            spellCheck={false}
            className="w-full bg-panel2 border border-border rounded px-3 py-2 mono text-xs"
          />
        </Card>
      </div>
      <div className="col-span-12 lg:col-span-4 space-y-4">
        <Card title="Available protocols">
          {protocols.data ? (
            <ul className="space-y-1 mono text-sm">
              {protocols.data.map((p) => (
                <li key={p} className={p === cfg.data.protocol ? "text-emerald-400" : ""}>
                  {p === cfg.data.protocol ? "★ " : "  "}
                  {p}
                </li>
              ))}
            </ul>
          ) : (
            "loading…"
          )}
          <p className="text-xs text-muted mt-3">
            Add a new one by dropping a <code className="mono">*.py</code> with a{" "}
            <code className="mono">BaseProtocol</code> subclass into{" "}
            <code className="mono">server/farm/protocols/</code>. The file's stem becomes the protocol id.
          </p>
        </Card>
        <Card title="Cheatsheet">
          <ul className="text-sm space-y-2 text-muted">
            <li><code className="mono">flag_format</code> – regex applied to exploit stdout.</li>
            <li><code className="mono">flag_lifetime</code> – seconds until QUEUED → EXPIRED.</li>
            <li><code className="mono">round_length</code> – clients pace exploit launches by this.</li>
            <li><code className="mono">submitter.period</code> + <code className="mono">batch_size</code> – submission rate-limit.</li>
            <li><code className="mono">protocols.{"<name>"}</code> – kwargs forwarded to the protocol class.</li>
            <li>
              <code className="mono">teams</code> – list of <code className="mono">{"{alias, ip}"}</code> or ranges{" "}
              <code className="mono">{"{from, to, alias?, ip?}"}</code> with{" "}
              <code className="mono">{"{i}"}</code>/<code className="mono">{"{i:02d}"}</code> templates.
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
