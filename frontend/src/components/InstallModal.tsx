import { useEffect, useState } from "react";

export function InstallModal({
  url,
  token,
  onClose,
}: {
  url: string;
  token?: string;
  onClose: () => void;
}) {
  const [revealToken, setRevealToken] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const base = url.replace(/\/$/, "");
  const tokenPart = revealToken && token ? token : "<TOKEN>";
  const downloadCmd = `curl -fsSL ${base}/install/farm-cli -o farm-cli && chmod +x ./farm-cli`;
  const loginCmd = `./farm-cli login ${base} --token ${tokenPart}`;
  const runCmd = `./farm-cli run /path/to/sploit.py`;
  const oneLiner = `${downloadCmd} && ${loginCmd}`;

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

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center p-6 overflow-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="install-cli-title"
    >
      <div
        className="bg-panel border border-border rounded-xl w-full max-w-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h2 id="install-cli-title" className="font-semibold">
            Install farm-cli on a client machine
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

        <div className="p-5 space-y-4 text-sm">
          <p className="text-muted">
            The CLI is a single self-contained file. The client machine only needs{" "}
            <code className="mono">python3</code> (≥ 3.11) — no pip, no venv, no root.
          </p>

          <Step n={1} title="Download">
            <CmdBox
              cmd={downloadCmd}
              copied={copied === "download"}
              onCopy={() => copy("download", downloadCmd)}
            />
            <div className="text-xs text-muted mt-1">
              Or open{" "}
              <a
                className="text-emerald-400 hover:underline mono"
                href={`${base}/install/farm-cli`}
              >
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
            {token ? (
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
            )}
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
            <div className="text-xs text-muted mb-1">
              One-liner (download + login):
            </div>
            <CmdBox
              cmd={oneLiner}
              copied={copied === "all"}
              onCopy={() => copy("all", oneLiner)}
            />
            <div className="text-xs text-muted mt-3">
              Plain-text version of these instructions:{" "}
              <a
                className="text-emerald-400 hover:underline mono"
                href={`${base}/install`}
              >
                {base}/install
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
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
