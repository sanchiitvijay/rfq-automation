import { Badge } from "../../components/ui";
import type { JobStatus } from "../../api/types";
import { STATUS_LABEL, STATUS_TONE } from "./status";

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}
