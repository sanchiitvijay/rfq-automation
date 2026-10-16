import type { Tone } from "../../components/ui";
import type { JobStatus } from "../../api/types";

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Processing",
  needs_review: "Needs review",
  ready: "Reviewed",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
};

export const STATUS_TONE: Record<JobStatus, Tone> = {
  queued: "neutral",
  running: "info",
  needs_review: "warning",
  ready: "success",
  sending: "info",
  sent: "success",
  failed: "danger",
};

export const SOURCE_LABEL = { extension: "Gmail", paste: "Pasted", upload: ".eml upload", mailbot: "Inbox bot" } as const;

export const isActive = (s: JobStatus) => s === "queued" || s === "running";
