/** Compact pager: "from–to of total", first/prev/next/last, optional page size.
 *  `page` is 0-based. Works for both server-side (Flags) and client-side
 *  (runs) paging — the caller just supplies the current page, size and total. */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
  sizes,
  unit = "",
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
  onPageSize?: (s: number) => void;
  sizes?: number[];
  unit?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const cur = Math.min(Math.max(0, page), pages - 1);
  const from = total === 0 ? 0 : cur * pageSize + 1;
  const to = Math.min(total, (cur + 1) * pageSize);

  const btn =
    "px-2 py-0.5 rounded border border-border hover:bg-panel2 " +
    "disabled:opacity-40 disabled:hover:bg-transparent";

  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="mono">
        {from}–{to} of {total}
        {unit ? ` ${unit}` : ""}
      </span>
      <div className="flex gap-1">
        <button className={btn} disabled={cur <= 0} onClick={() => onPage(0)} title="first">«</button>
        <button className={btn} disabled={cur <= 0} onClick={() => onPage(cur - 1)} title="previous">‹</button>
        <span className="mono px-1 self-center">{cur + 1}/{pages}</span>
        <button className={btn} disabled={cur >= pages - 1} onClick={() => onPage(cur + 1)} title="next">›</button>
        <button className={btn} disabled={cur >= pages - 1} onClick={() => onPage(pages - 1)} title="last">»</button>
      </div>
      {onPageSize && sizes && (
        <select
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
          className="bg-panel2 border border-border rounded px-1 py-0.5"
          title="rows per page"
        >
          {sizes.map((s) => (
            <option key={s} value={s}>{s}/page</option>
          ))}
        </select>
      )}
    </div>
  );
}
