import { ProgressBar } from "../../components/ui";
import type { JobSummary } from "../../api/types";
import { isActive } from "./status";

/** Phase text + bar + approximate time left while running; outcome once finished. */
export function JobProgress({ job }: { job: JobSummary }) {
  if (isActive(job.status)) {
    return <ProgressBar value={job.progress} label={job.phase || "Queued"} etaSeconds={job.eta_seconds} />;
  }
  if (job.status === "failed") {
    return <ProgressBar value={100} state="failed" label={job.error ? "Failed: " + job.error.slice(0, 60) : "Failed"} />;
  }
  return <span className="subtle">{job.phase}</span>;
}
