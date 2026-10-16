import { formatEta } from "../../lib/format";

interface Props {
  value: number;
  label?: string;
  etaSeconds?: number | null;
  state?: "active" | "done" | "failed";
}

export function ProgressBar({ value, label, etaSeconds, state = "active" }: Props) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  const eta = state === "active" ? formatEta(etaSeconds) : "";
  return (
    <div className="progress">
      <div className="progress__track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`progress__bar ${state === "done" ? "progress__bar--done" : ""} ${state === "failed" ? "progress__bar--failed" : ""}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="progress__meta">
        <span>{label}</span>
        {eta && <span className="num">{eta}</span>}
      </div>
    </div>
  );
}
