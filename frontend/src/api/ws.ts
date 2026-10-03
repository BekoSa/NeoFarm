import { Profile } from "./client";

export type FarmEvent = {
  kind: "flags" | "exploit" | "run" | string;
  payload: Record<string, unknown>;
};

export function wsUrl(profile: Profile): string {
  const base = profile.url.replace(/^http/, "ws").replace(/\/$/, "");
  return `${base}/ws`;
}

export function subscribe(
  profile: Profile,
  onEvent: (e: FarmEvent) => void,
  onStatus?: (s: "open" | "closed" | "error") => void,
): () => void {
  let stop = false;
  let ws: WebSocket | null = null;
  let backoff = 1000;

  const connect = () => {
    if (stop) return;
    const sock = new WebSocket(wsUrl(profile));
    ws = sock;
    sock.onopen = () => {
      // Auth is the first message, so the token never lands in access logs.
      sock.send(profile.token);
      backoff = 1000;
      onStatus?.("open");
    };
    sock.onclose = () => {
      onStatus?.("closed");
      if (!stop) setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
    sock.onerror = () => onStatus?.("error");
    sock.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch {
        /* ignore non-json */
      }
    };
  };

  connect();
  return () => {
    stop = true;
    ws?.close();
  };
}
