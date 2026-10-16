import { Badge } from "../../components/ui";
import type { JobStatus } from "../../api/types";
import { STATUS_TONE } from "./status";
import { useLabels } from "./useLabels";

export function StatusBadge({ status }: { status: JobStatus }) {
  const labels = useLabels();
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{labels.status(status)}</Badge>;
}
