import { ReactNode } from "react";

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="bg-panel border border-border rounded-xl">
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
