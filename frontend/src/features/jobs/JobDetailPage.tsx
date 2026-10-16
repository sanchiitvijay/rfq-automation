import { lazy, Suspense, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useLiveUpdates } from "../../api/events";
import { useDeleteJob, useJob, useRetry } from "../../api/hooks";
import { Button, Card, EmptyState, Menu, ProgressBar, Tabs, useToast, type MenuItem } from "../../components/ui";
import { formatTime } from "../../lib/format";
import { ImportDialog } from "../review/ImportDialog";
import { DownloadMenu } from "./DownloadMenu";
import { SendDialog } from "../send/SendDialog";
import { ActivityLog } from "./ActivityLog";
import { EmailPane } from "./EmailPane";
import { FlagsTable } from "./FlagsTable";
import { SourcesPanel } from "./SourcesPanel";
import { isActive } from "./status";
import { useLabels } from "./useLabels";
import { StatusBadge } from "./StatusBadge";
import { SummaryPanel } from "./SummaryPanel";
import "./detail.css";

const ReviewGrid = lazy(() => import("../review/ReviewGrid")); // the grid bundle loads only when needed

type Tab = "summary" | "review" | "sources" | "flags" | "activity";
const EMAIL_PREF = "rfq.showEmail";

function readPref(): boolean {
  try {
    return localStorage.getItem(EMAIL_PREF) !== "0";
  } catch {
    return true; // storage blocked (private window): just show the email
  }
}

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  useLiveUpdates(jobId);
  const retry = useRetry(jobId);
  const del = useDeleteJob();
  const toast = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("summary");
  const labels = useLabels();
  const [sending, setSending] = useState(false);
  const [importing, setImporting] = useState(false);
  const [showEmail, setShowEmailState] = useState(readPref);
  const setShowEmail = (v: boolean) => {
    setShowEmailState(v);
    try {
      localStorage.setItem(EMAIL_PREF, v ? "1" : "0");
    } catch {
      /* not remembered; fine */
    }
  };

  if (job.isLoading) return <p className="muted">Loading…</p>;
  if (job.isError || !job.data) {
    return (
      <EmptyState title="Request not found">
        <span>{job.error?.message}</span>
        <Link to="/">Back to all requests</Link>
      </EmptyState>
    );
  }
  const j = job.data;
  const active = isActive(j.status);
  const hasSheet = j.version > 0;
  const flags = j.report?.flags ?? [];
  const lastReview = [...j.events].reverse().find((e) => e.phase === "Reviewed" || e.phase === "Review reopened");
  const reviewedBy = lastReview?.phase === "Reviewed" ? `${lastReview.message} · ${formatTime(lastReview.ts)}` : undefined;
  const moreItems: MenuItem[] = [
    ...(hasSheet
      ? [{ key: "import", label: "Upload edited file…", description: ".xlsx, .xls or .csv; checked before anything changes", disabled: j.status === "sending", onSelect: () => setImporting(true) }]
      : []),
    { key: "email", label: showEmail ? "Hide the email" : "Show the email", description: "More room for the RFQ", onSelect: () => setShowEmail(!showEmail) },
    ...(!active && j.status !== "sending"
      ? [{
          key: "delete",
          label: "Delete request…",
          description: "The email and every RFQ version",
          danger: true,
          onSelect: () => {
            if (window.confirm("Delete this request, its email and all RFQ versions? This cannot be undone.")) {
              del.mutate(j.id, { onSuccess: () => navigate("/"), onError: (e) => toast(e.message, "error") });
            }
          },
        }]
      : []),
  ];

  return (
    <>
      <div className="page-head">
        <div className="detail-title">
          <Link to="/" className="subtle">
            ← All requests
          </Link>
          <h1>{j.subject || "(no subject)"}</h1>
          <p className="muted">
            {j.sender || "unknown sender"} · {labels.source(j.source)} · received {formatTime(j.created_at)}
          </p>
        </div>
        <div className="detail-actions">
          <StatusBadge status={j.status} />
          {hasSheet && <DownloadMenu jobId={j.id} version={j.version} />}
          {hasSheet && (
            <Button variant="primary" disabled={j.status === "sending"} onClick={() => setSending(true)}>
              {j.status === "sent" ? "Send again…" : "Send to POC…"}
            </Button>
          )}
          {j.status === "failed" && (
            <Button busy={retry.isPending} onClick={() => retry.mutate(undefined, { onError: (e) => toast(e.message, "error") })}>
              Retry
            </Button>
          )}
          {moreItems.length > 0 && <Menu label="More" variant="ghost" width={260} sections={[{ items: moreItems }]} />}
        </div>
      </div>

      {(active || j.status === "failed") && (
        <Card className="progress-card">
          <div className="progress-card__body">
            <ProgressBar
              value={active ? j.progress : 100}
              state={j.status === "failed" ? "failed" : "active"}
              label={active ? j.phase : `Failed: ${j.error ?? "unknown error"}`}
              etaSeconds={j.eta_seconds}
            />
            <ol className="steps">
              {j.events.slice(-6).map((e, i) => (
                <li key={i}>
                  <span className="num subtle">{formatTime(e.ts)}</span> {e.phase}
                </li>
              ))}
            </ol>
          </div>
        </Card>
      )}
      {j.status === "sending" && <div className="alert alert--info">Sending the RFQ… this page updates when it is delivered.</div>}
      {j.error && j.status !== "failed" && <div className="alert alert--error">{j.error}</div>}

      <div className={`detail-grid ${showEmail ? "" : "detail-grid--wide"}`}>
        {showEmail && <EmailPane job={j} onHide={() => setShowEmail(false)} />}
        <Card
          className="detail-main"
          title={
            <Tabs<Tab>
              value={tab}
              onChange={setTab}
              items={[
                { id: "summary", label: "Summary" },
                { id: "review", label: "Review & edit" },
                { id: "sources", label: "Sources" },
                { id: "flags", label: "Flags", count: flags.filter((f) => f.type !== "missing").length },
                { id: "activity", label: "Activity" },
              ]}
            />
          }
          actions={
            !showEmail ? (
              <Button size="sm" variant="ghost" onClick={() => setShowEmail(true)}>
                Show email
              </Button>
            ) : undefined
          }
        >
          {!hasSheet ? (
            <EmptyState title={active ? "Working on it" : "No RFQ yet"}>
              {active ? <span>{j.phase}</span> : <span>{j.error}</span>}
            </EmptyState>
          ) : tab === "summary" ? (
            <SummaryPanel job={j} />
          ) : tab === "review" ? (
            <Suspense fallback={<p className="muted">Loading the editor…</p>}>
              <ReviewGrid jobId={j.id} status={j.status} reviewedBy={reviewedBy} onImport={() => setImporting(true)} />
            </Suspense>
          ) : tab === "sources" ? (
            <SourcesPanel jobId={j.id} />
          ) : tab === "flags" ? (
            <FlagsTable flags={flags} />
          ) : (
            <ActivityLog job={j} />
          )}
        </Card>
      </div>
      {sending && <SendDialog job={j} onClose={() => setSending(false)} />}
      {importing && <ImportDialog jobId={j.id} onClose={() => setImporting(false)} />}
    </>
  );
}
