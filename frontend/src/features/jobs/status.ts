import type { Tone } from "../../components/ui";
import type { JobStatus } from "../../api/types";

/** Colour of each status badge (presentation only; the labels come from the server). */
export const STATUS_TONE: Record<JobStatus, Tone> = {
  queued: "neutral",
  running: "info",
  needs_review: "warning",
  ready: "success",
  sending: "info",
  sent: "success",
  failed: "danger",
};

export const isActive = (s: JobStatus) => s === "queued" || s === "running";
