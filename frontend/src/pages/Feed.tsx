import { useMemo, useState } from "react";
import { Profile } from "../api/client";
import { Card } from "../components/Card";
import {
  describe, EventLabel, EVENT_KINDS, fmtTime, LiveDot, useFeed,
} from "../components/events";

export function Feed({ profile }: { profile: Profile }) {
  // Keep a long history here — this page is dedicated to it.
  const { feed, live, clear } = useFeed(profile, 1000);
  const [kinds, setKinds] = useState<Set<string>>(new Set());

  const shown = useMemo(
    () => (kinds.size === 0 ? feed : feed.filter((e) => kinds.has(e.kind))),
    [feed, kinds],
  );

  const toggle = (k: string) =>
    setKinds((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });

  return (
    <Card
      title="Live feed"
      right={
        <div className="flex items-center gap-3 text-xs">
          <span className="text-muted mono">{shown.length}</span>
          <button onClick={clear} className="px-2 py-1 rounded border border-border hover:bg-panel2">
            clear
          </button>
          <LiveDot state={live} />
        </div>
      }
    >
      <div className="flex flex-wrap gap-1.5 mb-3">
        <Chip active={kinds.size === 0} onClick={() => setKinds(new Set())}>all</Chip>
        {EVENT_KINDS.map((k) => (
          <Chip key={k} active={kinds.has(k)} onClick={() => toggle(k)}>{k}</Chip>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="text-muted text-sm">waiting for events…</div>
      ) : (
        <ul className="space-y-1 max-h-[75vh] overflow-auto text-xs">
          {shown.map((e) => (
            <li key={e.seq} className="flex items-baseline gap-2 border-b border-border/50 pb-1">
              <span className="text-muted mono shrink-0">{fmtTime(e.at)}</span>
              <EventLabel kind={e.kind} />
              <span className="text-muted break-all">{describe(e)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Chip({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "px-2 py-0.5 rounded text-xs mono transition " +
        (active ? "bg-emerald-600 text-white" : "bg-panel2 text-muted hover:text-white")
      }
    >
      {children}
    </button>
  );
}
