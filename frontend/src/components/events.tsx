import { useEffect, useState } from "react";
import { Profile } from "../api/client";
import { FarmEvent, subscribe } from "../api/ws";

export type FeedItem = FarmEvent & { at: number; seq: number };
export type LiveState = "open" | "closed" | "error";

export const EVENT_KINDS = [
  "submit", "flags", "run", "exploit", "node", "requeue", "expired", "submitter_error", "pause",
] as const;

/** Subscribe to the live event stream, keeping the most recent `cap` events. */
export function useFeed(profile: Profile, cap = 120) {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [live, setLive] = useState<LiveState>("closed");
  useEffect(() => {
    let seq = 0;
    return subscribe(
      profile,
      (e) => setFeed((prev) => [{ ...e, at: Date.now(), seq: seq++ }, ...prev].slice(0, cap)),
      setLive,
    );
  }, [profile.url, profile.token, cap]);
  return { feed, live, clear: () => setFeed([]) };
}

export function fmtTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

const EVENT_STYLE: Record<string, string> = {
  submit: "bg-emerald-800 text-emerald-100",
  flags: "bg-blue-800 text-blue-100",
  run: "bg-sky-900 text-sky-100",
  exploit: "bg-indigo-800 text-indigo-100",
  node: "bg-teal-800 text-teal-100",
  requeue: "bg-yellow-800 text-yellow-100",
  expired: "bg-gray-700 text-gray-200",
  submitter_error: "bg-pink-800 text-pink-100",
  pause: "bg-orange-800 text-orange-100",
};

export function EventLabel({ kind }: { kind: string }) {
  const cls = EVENT_STYLE[kind] || "bg-gray-700 text-gray-200";
  return <span className={"px-1.5 py-0.5 rounded mono shrink-0 " + cls}>{kind}</span>;
}

export function describe(e: FarmEvent): string {
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
    case "node": {
      const who = p.name ?? p.hostname ?? "node";
      if (p.action === "task") return `${who}: task ${p.sploit} pushed`;
      if (p.action === "updated") return `${who} ${p.enabled ? "enabled" : "disabled"}`;
      return `${who} ${p.action ?? "event"}`;
    }
    case "requeue":
      return `${p.flags} flag(s) requeued from ${p.from}`;
    case "expired":
      return `${p.flags} flag(s) expired`;
    case "submitter_error":
      return `jury gave no verdict for ${p.flags} flag(s): ${p.error ?? "?"}`;
    case "pause":
      return p.paused ? "farm paused (break)" : "farm resumed";
    default:
      return JSON.stringify(p);
  }
}

export function LiveDot({ state }: { state: LiveState }) {
  const map = { open: "bg-emerald-400", closed: "bg-gray-500", error: "bg-red-400" };
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted">
      <span className={"w-2 h-2 rounded-full " + map[state]} />
      {state === "open" ? "live" : state}
    </span>
  );
}
