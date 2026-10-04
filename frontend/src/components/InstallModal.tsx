import { useEffect, useState } from "react";

const NODE_IMAGE = "ghcr.io/bekosa/neofarm-node:latest";

export function InstallModal({
  url,
  token,
  onClose,
}: {
  url: string;
  token?: string;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"cli" | "node">("cli");
  const [revealToken, setRevealToken] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const base = url.replace(/\/$/, "");
  const tokenPart = revealToken && token ? token : "<TOKEN>";

  // --- CLI ---
  const downloadCmd = `curl -fsSL ${base}/install/farm-cli -o farm-cli && chmod +x ./farm-cli`;
  const loginCmd = `./farm-cli login ${base} --token ${tokenPart}`;
  const runCmd = `./farm-cli run /path/to/sploit.py`;
  const oneLiner = `${downloadCmd} && ${loginCmd}`;

  // --- Node (Docker) ---
  const nodeRun =
    `docker run -d --name neofarm-node --restart unless-stopped --network host \\\n` +
    `  -e FARM_URL=${base} \\\n` +
    `  -e FARM_TOKEN=${tokenPart} \\\n` +
    `  -e NODE_NAME=$(hostname) \\\n` +
    `  -v neofarm-node:/root/.config/farm-cli \\\n` +
    `  ${NODE_IMAGE}`;

  const copy = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied("err");
      setTimeout(() => setCopied(null), 1500);
    }
  };

  const RevealToggle = () =>
    token ? (
      <label className="flex items-center gap-2 text-xs text-muted mt-2 cursor-pointer">
        <input
          type="checkbox"
          checked={revealToken}
          onChange={(e) => setRevealToken(e.target.checked)}
        />
        Paste my token into the command (otherwise{" "}
        <code className="mono">&lt;TOKEN&gt;</code> stays a placeholder)
      </label>
    ) : (
      <div className="text-xs text-muted mt-2">
        Replace <code className="mono">&lt;TOKEN&gt;</code> with the farm token.
      </div>
    );

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center p-6 overflow-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="install-title"
    >
      <div
        className="bg-panel border border-border rounded-xl w-full max-w-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h2 id="install-title" className="font-semibold">
            Install a farm client
          </h2>
          <button
            type="button"
            className="text-muted hover:text-white text-lg leading-none"
            onClick={onClose}
            aria-label="close"
          >
            ×
          </button>
        </header>

        <div className="px-5 pt-4">
          <div className="inline-flex rounded-lg border border-border overflow-hidden text-sm">
            <ModeTab active={mode === "cli"} onClick={() => setMode("cli")}>
              CLI
            </ModeTab>
            <ModeTab active={mode === "node"} onClick={() => setMode("node")}>
              Node (Docker)
            </ModeTab>
          </div>
        </div>

        {mode === "cli" ? (
          <div className="p-5 space-y-4 text-sm">
            <p className="text-muted">
              Run exploits from your own shell. The CLI is a single self-contained
              file — the client machine only needs <code className="mono">python3</code>{" "}
              (≥ 3.11), no pip, no venv, no root.
            </p>

            <Step n={1} title="Download">
              <CmdBox
                cmd={downloadCmd}
                copied={copied === "download"}
                onCopy={() => copy("download", downloadCmd)}
              />
              <div className="text-xs text-muted mt-1">
                Or open{" "}
                <a className="text-emerald-400 hover:underline mono" href={`${base}/install/farm-cli`}>
                  {base}/install/farm-cli
                </a>{" "}
                in a browser to download manually.
              </div>
            </Step>

            <Step n={2} title="Login">
              <CmdBox
                cmd={loginCmd}
                copied={copied === "login"}
                onCopy={() => copy("login", loginCmd)}
              />
              <RevealToggle />
            </Step>

            <Step n={3} title="Run an exploit">
              <CmdBox
                cmd={runCmd}
                copied={copied === "run"}
                onCopy={() => copy("run", runCmd)}
              />
              <div className="text-xs text-muted mt-1">
                The script is invoked once per round against every team. Output matching{" "}
                <code className="mono">flag_format</code> is shipped to the farm automatically.
              </div>
            </Step>

            <div className="border-t border-border pt-4">
              <div className="text-xs text-muted mb-1">One-liner (download + login):</div>
              <CmdBox
                cmd={oneLiner}
                copied={copied === "all"}
                onCopy={() => copy("all", oneLiner)}
              />
              <div className="text-xs text-muted mt-3">
                Plain-text version:{" "}
                <a className="text-emerald-400 hover:underline mono" href={`${base}/install`}>
                  {base}/install
                </a>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-5 space-y-4 text-sm">
            <p className="text-muted">
              Run this machine as a farm-managed <b>node</b>: it registers itself and
              runs whatever exploits you push to it from the <b>Nodes</b> tab — the same
              way <code className="mono">farm-cli run</code> works, but driven centrally.
              Only <code className="mono">docker</code> is required.
            </p>

            <Step n={1} title="Start the node">
              <CmdBox
                cmd={nodeRun}
                copied={copied === "node-run"}
                onCopy={() => copy("node-run", nodeRun)}
              />
              <RevealToggle />
            </Step>

            <Step n={2} title="Push exploits from the UI">
              <div className="text-xs text-muted">
                Open the <b>Nodes</b> tab — the node appears <span className="text-emerald-400">online</span>{" "}
                within a few seconds. Expand it and push an exploit (name + script + args);
                it starts running against every team each round.
              </div>
            </Step>

            <div className="border-t border-border pt-4 space-y-2 text-xs text-muted">
              <div>
                <b className="text-ink">Identity:</b> the{" "}
                <code className="mono">neofarm-node</code> volume keeps this node's id, so a
                restart rejoins as the same node (delete it to get a fresh one).
              </div>
              <div>
                <b className="text-ink">Extra deps:</b> the image ships{" "}
                <code className="mono">requests</code> + <code className="mono">pycryptodome</code>;
                add more with <code className="mono">-e PIP_PACKAGES="pwntools beautifulsoup4"</code>.
              </div>
              <div>
                <b className="text-ink">Networking:</b> <code className="mono">--network host</code>{" "}
                reaches the game network like the host. On Docker Desktop (mac/Windows) drop it.
              </div>
              <div>
                Stop &amp; remove: <code className="mono">docker rm -f neofarm-node</code>. Logs:{" "}
                <code className="mono">docker logs -f neofarm-node</code>.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "px-4 py-1.5 transition " +
        (active ? "bg-emerald-600 text-white" : "text-muted hover:text-white hover:bg-panel2")
      }
    >
      {children}
    </button>
  );
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="font-medium mb-2">
        <span className="inline-block w-5 h-5 rounded-full bg-emerald-600 text-white text-xs text-center leading-5 mr-2">
          {n}
        </span>
        {title}
      </div>
      <div className="ml-7">{children}</div>
    </div>
  );
}

function CmdBox({
  cmd,
  copied,
  onCopy,
}: {
  cmd: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-stretch gap-2">
      <code className="flex-1 bg-panel2 border border-border rounded px-3 py-2 mono text-xs whitespace-pre-wrap break-all">
        {cmd}
      </code>
      <button
        type="button"
        className="px-3 py-2 rounded border border-border hover:bg-panel2 text-xs whitespace-nowrap"
        onClick={onCopy}
      >
        {copied ? "copied!" : "copy"}
      </button>
    </div>
  );
}
