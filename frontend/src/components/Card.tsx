import { ReactNode } from "react";

export function Card({ title, children, right, className }: { title?: string; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={"bg-panel border border-border rounded-xl " + (className ?? "")}>
      {title && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="font-semibold">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
