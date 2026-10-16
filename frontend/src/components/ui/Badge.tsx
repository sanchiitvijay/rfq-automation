import type { ReactNode } from "react";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "missing" | "suspicious";

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}
