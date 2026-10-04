import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export type Accessor<T> = (row: T) => string | number | null | undefined;

export interface Sort {
  key: string;
  dir: SortDir;
  toggle: (key: string) => void;
}

/** Client-side column sorting for already-loaded rows. */
export function useSort<T>(
  rows: T[],
  accessors: Record<string, Accessor<T>>,
  initial: { key: string; dir: SortDir },
): { sorted: T[]; sort: Sort } {
  const [key, setKey] = useState(initial.key);
  const [dir, setDir] = useState<SortDir>(initial.dir);

  const sorted = useMemo(() => {
    const get = accessors[key];
    if (!get) return rows;
    const arr = [...rows];
    arr.sort((a, b) => {
      const av = get(a);
      const bv = get(b);
      let c: number;
      if (typeof av === "number" && typeof bv === "number") {
        c = av - bv;
      } else {
        c = String(av ?? "").localeCompare(String(bv ?? ""), undefined, {
          numeric: true,
          sensitivity: "base",
        });
      }
      return dir === "asc" ? c : -c;
    });
    return arr;
    // accessors is a stable literal per call site; key/dir/rows drive it.
  }, [rows, key, dir]);

  const toggle = (k: string) => {
    if (k === key) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setKey(k);
      setDir("asc");
    }
  };

  return { sorted, sort: { key, dir, toggle } };
}

/** A clickable <th> that drives a `useSort` result. */
export function SortHeader({
  label, sortKey, sort, align = "left", className = "",
}: {
  label: string;
  sortKey: string;
  sort: Sort;
  align?: "left" | "right";
  className?: string;
}) {
  const active = sort.key === sortKey;
  const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "↕";
  return (
    <th
      onClick={() => sort.toggle(sortKey)}
      className={
        "font-medium cursor-pointer select-none hover:text-white " +
        (align === "right" ? "text-right" : "text-left") +
        " " +
        className
      }
      title="sort"
    >
      {label}
      <span className={"ml-1 text-xs " + (active ? "" : "opacity-30")}>{arrow}</span>
    </th>
  );
}
