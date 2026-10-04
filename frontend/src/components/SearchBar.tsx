/** Shared search input: 🔍 icon, clear button, consistent styling. */
export function SearchBar({
  value, onChange, placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-panel2 border border-border rounded-lg pl-9 pr-9 py-2 text-sm"
      />
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted">🔍</span>
      {value && (
        <button
          onClick={() => onChange("")}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-white text-sm"
          title="clear"
        >
          ✕
        </button>
      )}
    </div>
  );
}

/** "shown / total" when filtering, otherwise just the total. */
export function countLabel(shown: number, total: number | undefined, filtering: boolean): string {
  if (total === undefined) return "";
  return filtering ? `${shown} / ${total}` : String(total);
}
