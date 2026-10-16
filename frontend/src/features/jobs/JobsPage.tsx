import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { useLiveUpdates } from "../../api/events";
import { useJobs } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, Pagination } from "../../components/ui";
import { formatTime, pct, senderName } from "../../lib/format";
import { FiltersPanel } from "./FiltersPanel";
import { JobProgress } from "./JobProgress";
import { NewJobPanel } from "./NewJobPanel";
import { StatusBadge } from "./StatusBadge";
import { useJobFilters } from "./useJobFilters";
import { useLabels } from "./useLabels";
import "./jobs.css";

export function JobsPage() {
  const { filters, set, clear, active } = useJobFilters();
  const jobs = useJobs(filters);
  const live = useLiveUpdates();
  const labels = useLabels();
  const navigate = useNavigate();
  const [showNew, setShowNew] = useState(false);
  const page = jobs.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>RFQ requests</h1>
          <p className="muted">Emails from Gmail, pasted or uploaded. Each one runs on its own worker.</p>
        </div>
        {!showNew && (
          <Button variant="primary" onClick={() => setShowNew(true)}>
            New request
          </Button>
        )}
      </div>
      {showNew && <NewJobPanel onDone={() => setShowNew(false)} />}
      <FiltersPanel filters={filters} set={set} clear={clear} active={active} />
      <Card
        title={<h3>{page ? `${page.total} ${page.total === 1 ? "request" : "requests"}` : "Requests"}</h3>}
        actions={<span className="subtle">{jobs.isFetching ? "Updating…" : live === "live" ? "Live updates" : "Refreshing every 3 s"}</span>}
      >
        {filters.from && filters.to && filters.from > filters.to ? (
          <div className="alert alert--warning">The “Received from” date is after “Received to”. Fix the dates to see results.</div>
        ) : jobs.isLoading ? (
          <p className="muted">Loading…</p>
        ) : jobs.isError ? (
          <div className="alert alert--error">
            {jobs.error instanceof ApiError && jobs.error.status === 422 ? `Check the filters: ${jobs.error.message}` : jobs.error.message}
          </div>
        ) : !page || page.items.length === 0 ? (
          <EmptyState title={active.length ? "No requests match these filters" : "No requests yet"}>
            {active.length ? (
              <Button size="sm" onClick={clear}>
                Clear filters
              </Button>
            ) : (
              <span>Open an RFQ email in Gmail and click the RFQ Agent extension, or use New request.</span>
            )}
          </EmptyState>
        ) : (
          <>
            <div className="table-scroll">
              <table className={`table table--clickable jobs-table ${jobs.isPlaceholderData ? "is-stale" : ""}`}>
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
                  {page.items.map((j) => (
                    <tr key={j.id} onClick={() => navigate(`/jobs/${j.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/jobs/${j.id}`)}>
                      <td className="subject">
                        <strong>{j.subject || "(no subject)"}</strong>
                        <span className="subtle">
                          {senderName(j.sender) || "unknown sender"} · {labels.source(j.source)}
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
            </div>
            <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={(p) => set({ page: String(p) })} />
          </>
        )}
      </Card>
    </>
  );
}
