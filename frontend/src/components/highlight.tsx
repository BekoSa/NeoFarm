/** Wrap case-insensitive matches of `needle` in `text` with a highlight mark. */
export function highlight(text: string | null | undefined, needle: string) {
  const s = text ?? "";
  if (!needle || !s) return s;
  const lower = s.toLowerCase();
  const out: (string | JSX.Element)[] = [];
  let i = 0;
  let k = 0;
  while (i < s.length) {
    const hit = lower.indexOf(needle, i);
    if (hit === -1) {
      out.push(s.slice(i));
      break;
    }
    if (hit > i) out.push(s.slice(i, hit));
    out.push(
      <mark key={k++} className="bg-yellow-500/30 text-inherit rounded-sm">
        {s.slice(hit, hit + needle.length)}
      </mark>,
    );
    i = hit + needle.length;
  }
  return <>{out}</>;
}
