import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "md" | "sm";
  busy?: boolean;
}

export function Button({ variant = "secondary", size = "md", busy, className = "", children, disabled, ...rest }: Props) {
  return (
    <button
      type="button"
      className={`btn btn--${variant} ${size === "sm" ? "btn--sm" : ""} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? "Working…" : children}
    </button>
  );
}
