const COLORS: Record<string, string> = {
  ACCEPTED: "bg-emerald-700 text-emerald-100",
  REJECTED: "bg-red-800 text-red-100",
  QUEUED: "bg-yellow-800 text-yellow-100",
  PENDING: "bg-blue-800 text-blue-100",
  EXPIRED: "bg-gray-700 text-gray-200",
  DUPLICATE: "bg-purple-800 text-purple-100",
  ERROR: "bg-pink-800 text-pink-100",
};

export function StatusPill({ status }: { status: string }) {
  const cls = COLORS[status] || "bg-gray-700 text-gray-200";
  return (
    <span className={"px-2 py-0.5 rounded text-xs mono " + cls}>{status}</span>
  );
}
