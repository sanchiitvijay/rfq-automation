import { Fragment, useMemo } from "react";
import type { JobDetail } from "../../api/types";
import { Button, Card } from "../../components/ui";

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The email exactly as received, rendered as plain text (never as HTML, so nothing in the email can
 * run in the page), with every product token the agent picked up highlighted.
 */
export function EmailPane({ job, onHide }: { job: JobDetail; onHide?: () => void }) {
  const tokens = useMemo(() => [...new Set(job.items.map((i) => i.raw_token))].sort((a, b) => b.length - a.length), [job.items]);
  const parts = useMemo(() => {
    if (!tokens.length) return [job.email.body];
    const re = new RegExp(`(${tokens.map(escapeRe).join("|")})`, "g");
    return job.email.body.split(re);
  }, [job.email.body, tokens]);
  const kind = useMemo(() => new Map(job.items.map((i) => [i.raw_token, i])), [job.items]);

  return (
    <Card
      title="Email as received"
      className="email-pane"
      actions={onHide && <Button size="sm" variant="ghost" onClick={onHide} title="Give the RFQ the full width">Hide</Button>}
    >
      <dl className="email-meta">
        <dt>From</dt>
        <dd>{job.email.sender || <span className="subtle">unknown</span>}</dd>
        <dt>Subject</dt>
        <dd>{job.email.subject}</dd>
        {job.email.date && (
          <>
            <dt>Date</dt>
            <dd>{job.email.date}</dd>
          </>
        )}
        {job.email.attachments.length > 0 && (
          <>
            <dt>Attachments</dt>
            <dd>{job.email.attachments.join(", ")}</dd>
          </>
        )}
      </dl>
      {!job.email.has_raw && job.source !== "paste" && (
        <div className="alert alert--warning">Only the visible text was received; attachments were not included.</div>
      )}
      <pre className="email-body">
        {parts.map((part, i) => {
          const item = kind.get(part);
          if (!item) return <Fragment key={i}>{part}</Fragment>;
          return (
            <mark key={i} className={`token token--${item.lookup_status === "Not found" ? "missing" : item.kind}`} title={`${item.kind === "competitor" ? "Competitor / unknown code" : "Ferguson ID"} · ${item.lookup_status || "pending"}`}>
              {part}
            </mark>
          );
        })}
      </pre>
      {job.items.some((i) => i.origin.startsWith("attachment:")) && (
        <p className="subtle">
          {job.items.filter((i) => i.origin.startsWith("attachment:")).length} IDs were read from the attachment.
        </p>
      )}
    </Card>
  );
}
