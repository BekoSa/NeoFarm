import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { buildApi, Profile } from "../api/client";
import { Card } from "../components/Card";

export function Manual({ profile }: { profile: Profile }) {
  const api = buildApi(profile);
  const [text, setText] = useState("");
  const [sploit, setSploit] = useState("manual");
  const [team, setTeam] = useState("");
  const [result, setResult] = useState<{ new: number; duplicate: number; invalid: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: async () =>
      (await api.post("/api/flags/manual", { text, sploit, team: team || null })).data,
    onSuccess: (data) => {
      setResult(data);
      setErr(null);
      setText("");
    },
    onError: (e: any) => setErr(e?.response?.data?.detail || e.message),
  });

  return (
    <Card title="Manual flag submission">
      <div className="grid grid-cols-2 gap-3 mb-3">
        <input
          value={sploit}
          onChange={(e) => setSploit(e.target.value)}
          placeholder="sploit (default: manual)"
          className="bg-panel2 border border-border rounded px-3 py-2 mono text-sm"
        />
        <input
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          placeholder="team alias (optional)"
          className="bg-panel2 border border-border rounded px-3 py-2 mono text-sm"
        />
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        placeholder="paste exploit output, log, or just a list of flags…"
        className="w-full bg-panel2 border border-border rounded px-3 py-2 mono text-sm"
      />
      <div className="flex items-center gap-3 mt-3">
        <button
          disabled={submit.isPending || !text.trim()}
          onClick={() => submit.mutate()}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 rounded font-medium"
        >
          {submit.isPending ? "submitting…" : "Extract & queue"}
        </button>
        {result && (
          <span className="text-sm text-muted">
            queued {" "}
            <span className="text-emerald-400 mono">{result.new}</span>, dup{" "}
            <span className="text-yellow-400 mono">{result.duplicate}</span>, invalid{" "}
            <span className="text-red-400 mono">{result.invalid}</span>
          </span>
        )}
        {err && <span className="text-red-400 text-sm">{err}</span>}
      </div>
      <p className="text-xs text-muted mt-3">
        Flags are extracted with the configured regex; duplicates are silently dropped.
        Submission to the jury happens via the submitter on its next tick.
      </p>
    </Card>
  );
}
