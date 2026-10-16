import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLiveUpdates } from "../../api/events";
import { useJobs } from "../../api/hooks";
import type { JobStatus } from "../../api/types";
import { Badge, Button, Card, EmptyState } from "../../components/ui";
import { formatTime, pct, senderName } from "../../lib/format";
import { JobProgress } from "./JobProgress";
import { NewJobPanel } from "./NewJobPanel";
import { SOURCE_LABEL } from "./status";
import { StatusBadge } from "./StatusBadge";
import "./jobs.css";

const FILTERS: { id: "all" | "active" | "review" | "sent" | "failed"; label: string; match: (s: JobStatus) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "active", label: "Processing", match: (s) => s === "queued" || s === "running" },
  { id: "review", label: "To review", match: (s) => s === "needs_review" || s === "ready" },
  { id: "sent", label: "Sent", match: (s) => s === "sent" || s === "sending" },
  { id: "failed", label: "Failed", match: (s) => s === "failed" },
];

export function JobsPage() {
  const jobs = useJobs();
  const live = useLiveUpdates();
  const navigate = useNavigate();
  const [showNew, setShowNew] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  const visible = useMemo(() => {
    const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0]!;
    return (jobs.data ?? []).filter((j) => f.match(j.status));
  }, [jobs.data, filter]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>RFQ requests</h1>
          <p className="muted">Emails sent from Gmail, pasted or uploaded. Each runs on its own worker; nothing waits in line behind another request.</p>
        </div>
        {!showNew && (
          <Button variant="primary" onClick={() => setShowNew(true)}>
            New request
          </Button>
        )}
      </div>
      {showNew && <NewJobPanel onDone={() => setShowNew(false)} />}
      <Card
        title={
          <div className="jobs-filters" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" className="chip" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.label}
              </button>
            ))}
          </div>
        }
        actions={<span className="subtle">{live === "live" ? "Live updates" : "Refreshing every 3 s"}</span>}
      >
        {jobs.isLoading ? (
          <p className="muted">Loading…</p>
        ) : jobs.isError ? (
          <div className="alert alert--error">{jobs.error.message}</div>
        ) : visible.length === 0 ? (
          <EmptyState title={filter === "all" ? "No requests yet" : "Nothing here"}>
            {filter === "all" && <span>Open an RFQ email in Gmail and click the RFQ Agent extension, or use New request.</span>}
          </EmptyState>
        ) : (
          <table className="table table--clickable jobs-table">
            <thead>
              <tr>
                <th>Request</th>
                <th>Status</th>
                <th>Progress</th>
                <th className="hide-sm">Products</th>
                <th className="hide-sm">Fill rate</th>
                <th className="hide-sm">Received</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((j) => (
                <tr key={j.id} onClick={() => navigate(`/jobs/${j.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/jobs/${j.id}`)}>
                  <td className="subject">
                    <strong>{j.subject || "(no subject)"}</strong>
                    <span className="subtle">
                      {senderName(j.sender) || "unknown sender"} · {SOURCE_LABEL[j.source]}
                    </span>
                  </td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td>
                    <JobProgress job={j} />
                  </td>
                  <td className="hide-sm num">
                    {j.requested > 0 ? (
                      <span className="counts">
                        <span>
                          {j.found}/{j.requested} found
                        </span>
                        {j.not_found > 0 && <Badge tone="danger">{j.not_found} not found</Badge>}
                      </span>
                    ) : (
                      <span className="subtle">–</span>
                    )}
                  </td>
                  <td className="hide-sm num">{pct(j.fill_rate)}</td>
                  <td className="hide-sm subtle num">{formatTime(j.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
