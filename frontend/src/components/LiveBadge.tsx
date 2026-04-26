import { useEffect, useState } from "react";
import { Profile } from "../api/client";
import { subscribe } from "../api/ws";

export function LiveBadge({ profile }: { profile: Profile }) {
  const [status, setStatus] = useState<"open" | "closed" | "error">("closed");

  useEffect(() => {
    return subscribe(profile, () => {}, setStatus);
  }, [profile]);

  const color =
    status === "open" ? "bg-emerald-500" : status === "error" ? "bg-red-500" : "bg-yellow-500";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={"w-2 h-2 rounded-full " + color} />
      <span>{status}</span>
    </div>
  );
}
