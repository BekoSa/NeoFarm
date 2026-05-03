import { useEffect, useMemo, useState } from "react";
import { buildApi, clearProfile, defaultUrl, loadProfile, Profile, saveProfile } from "./api/client";
import { Dashboard } from "./pages/Dashboard";
import { Flags } from "./pages/Flags";
import { Exploits } from "./pages/Exploits";
import { Config } from "./pages/Config";
import { Manual } from "./pages/Manual";
import { LiveBadge } from "./components/LiveBadge";

type Tab = "dashboard" | "flags" | "exploits" | "manual" | "config";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "flags", label: "Flags" },
  { id: "exploits", label: "Exploits" },
  { id: "manual", label: "Manual submit" },
  { id: "config", label: "Config" },
];

export default function App() {
  const [profile, setProfile] = useState<Profile | null>(loadProfile);
  const [tab, setTab] = useState<Tab>("dashboard");

  if (!profile) {
    return <Login onLogin={(p) => { saveProfile(p); setProfile(p); }} />;
  }

  return (
    <Shell profile={profile} onLogout={() => { clearProfile(); setProfile(null); }} tab={tab} setTab={setTab}>
      {tab === "dashboard" && <Dashboard profile={profile} />}
      {tab === "flags" && <Flags profile={profile} />}
      {tab === "exploits" && <Exploits profile={profile} />}
      {tab === "manual" && <Manual profile={profile} />}
      {tab === "config" && <Config profile={profile} />}
    </Shell>
  );
}

function Shell({
  profile, onLogout, tab, setTab, children,
}: {
  profile: Profile;
  onLogout: () => void;
  tab: Tab;
  setTab: (t: Tab) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-panel">
        <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="font-bold text-lg">🐄 Farm</div>
          <nav className="flex gap-2">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={
                  "px-3 py-1.5 rounded text-sm transition " +
                  (tab === t.id
                    ? "bg-emerald-600 text-white"
                    : "text-muted hover:text-white hover:bg-panel2")
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-muted">
            <LiveBadge profile={profile} />
            <span className="mono">{profile.url}</span>
            <button
              className="text-xs px-2 py-1 rounded border border-border hover:bg-panel2"
              onClick={onLogout}
            >
              logout
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto p-6">{children}</main>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (p: Profile) => void }) {
  const [url, setUrl] = useState(defaultUrl());
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const api = buildApi({ url, token });
      await api.get("/health");
      await api.get("/api/config/protocols");
      onLogin({ url: url.replace(/\/$/, ""), token });
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "connection failed");
    } finally {
      setBusy(false);
    }
  };

  const yearLabel = useMemo(() => new Date().getFullYear(), []);
  useEffect(() => {
    document.title = "Farm — login";
  }, []);

  return (
    <div className="min-h-full flex items-center justify-center">
      <form onSubmit={submit} className="w-[360px] bg-panel p-6 rounded-xl border border-border">
        <h1 className="text-xl font-bold mb-4">🐄 Farm</h1>
        <label className="block text-sm text-muted mb-1">Server URL</label>
        <input
          className="w-full bg-panel2 border border-border rounded px-3 py-2 mb-3 mono text-sm"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://farm-host:5000"
        />
        <label className="block text-sm text-muted mb-1">Token</label>
        <input
          className="w-full bg-panel2 border border-border rounded px-3 py-2 mb-3 mono text-sm"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          type="password"
          placeholder="X-Farm-Token"
        />
        {err && <div className="text-red-400 text-sm mb-3">{err}</div>}
        <button
          disabled={busy || !token || !url}
          className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-3 py-2 rounded font-medium"
        >
          {busy ? "connecting…" : "Connect"}
        </button>
        <div className="text-xs text-muted mt-4">© {yearLabel} farm</div>
      </form>
    </div>
  );
}
