/** "≈ 40 s left", "≈ 2 min left"; empty when unknown. */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds <= 0) return "";
  if (seconds < 60) return `≈ ${Math.max(5, Math.round(seconds / 5) * 5)} s left`;
  const minutes = Math.round(seconds / 60);
  return `≈ ${minutes} min left`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function senderName(sender: string): string {
  const m = sender.match(/^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/);
  return (m?.[1] ?? sender).trim();
}

export function senderAddress(sender: string): string {
  const m = sender.match(/<([^>]+)>/);
  return (m?.[1] ?? sender).trim();
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

export function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
