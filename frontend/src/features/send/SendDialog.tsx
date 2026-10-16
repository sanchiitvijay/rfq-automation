import { useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import { useMailTest, useSend, useSheet } from "../../api/hooks";
import type { JobDetail } from "../../api/types";
import { Button, Field, Modal, useToast } from "../../components/ui";
import { newKey, pct, senderAddress, senderName } from "../../lib/format";
import "./send.css";

const EMAIL = /^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]{2,}$/;

function defaultBody(job: JobDetail, name: string): string {
  const notFound = job.items.filter((i) => i.lookup_status === "Not found");
  const lines = [`Hi ${name || "there"},`, "", `Please find the RFQ attached: ${job.found} of ${job.requested} products found.`];
  if (notFound.length) {
    lines.push("", "Not found (left blank, nothing guessed):", ...notFound.map((i) => `  - ${i.product_id}`));
  }
  lines.push("", "Every value has its source on the Sources sheet, and the Summary sheet lists anything still open.", "", "Regards,", "Ferguson Sourcing");
  return lines.join("\n");
}

interface Props {
  job: JobDetail;
  onClose: () => void;
}

/** Asks for the point of contact, warns about gaps, shows a final confirmation, then sends once. */
export function SendDialog({ job, onClose }: Props) {
  const sheet = useSheet(job.id, true);
  const send = useSend(job.id);
  const toast = useToast();
  const idempotencyKey = useMemo(newKey, []); // one key per dialog: double clicks never send twice
  const [to, setTo] = useState(senderAddress(job.sender));
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState(job.subject.toLowerCase().startsWith("re:") ? job.subject : `Re: ${job.subject}`);
  const [body, setBody] = useState(() => defaultBody(job, senderName(job.sender).split(" ")[0] ?? ""));
  const [confirmIncomplete, setConfirmIncomplete] = useState(false);
  const [resend, setResend] = useState(false);
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [serverError, setServerError] = useState<string | null>(null);
  const mailTest = useMailTest();

  const inc = sheet.data?.incomplete;
  const ccList = cc.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
  const toError = to && !EMAIL.test(to.trim()) ? "Enter a valid email address" : null;
  const ccError = ccList.some((c) => !EMAIL.test(c)) ? "One of the CC addresses is not valid" : null;
  const needsConfirm = inc ? !inc.complete : false;
  const alreadySent = job.status === "sent";
  const canContinue =
    !!to.trim() && !toError && !ccError && subject.trim() && body.trim() && (!needsConfirm || confirmIncomplete) && (!alreadySent || resend);
  const fileName = job.version <= 1 ? "RFQ.xlsx" : `RFQ_v${job.version}.xlsx`;
  const missingCount = inc ? Object.values(inc.missing).reduce((n, c) => n + c.length, 0) : 0;

  const submit = () => {
    setServerError(null);
    send.mutate(
      { to: to.trim(), cc: ccList, subject: subject.trim(), body, confirm_incomplete: confirmIncomplete, resend, idempotency_key: idempotencyKey },
      {
        onSuccess: () => {
          toast(`Sending to ${to.trim()}…`, "success");
          onClose();
        },
        onError: (e) => {
          setServerError(e instanceof ApiError ? e.message : String(e));
          setStep("form");
        },
      },
    );
  };

  return (
    <Modal
      title={step === "form" ? "Send RFQ to the point of contact" : "Confirm and send"}
      onClose={onClose}
      footer={
        step === "form" ? (
          <>
            <Button
              variant="ghost"
              className="send__test"
              busy={mailTest.isPending}
              busyLabel="Logging in…"
              title="Logs in to the mail server with BOT_EMAIL / BOT_PASSWORD; sends nothing"
              onClick={() => mailTest.mutate()}
            >
              Test mail login
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!canContinue || sheet.isLoading} onClick={() => setStep("confirm")}>
              Review before sending
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={() => setStep("form")}>
              Back
            </Button>
            <Button variant="primary" busy={send.isPending} onClick={submit}>
              Send now
            </Button>
          </>
        )
      }
    >
      {serverError && <div className="alert alert--error">{serverError}</div>}
      {job.error?.startsWith("Sending failed") && !serverError && (
        <div className="alert alert--error">Last attempt: {job.error}</div>
      )}
      {mailTest.data && (
        <div className={`alert ${mailTest.data.ok ? "alert--info" : "alert--error"}`}>
          {mailTest.data.ok ? "Mail settings work: " : "Mail settings problem: "}
          {mailTest.data.detail}
        </div>
      )}
      {mailTest.isError && <div className="alert alert--error">{mailTest.error.message}</div>}
      {step === "form" ? (
        <>
          <Field label="To (point of contact)" htmlFor="send-to" error={toError} hint="Pre-filled with the person who sent the request">
            <input id="send-to" className="input" type="email" value={to} onChange={(e) => setTo(e.target.value)} aria-invalid={!!toError} autoComplete="email" />
          </Field>
          <Field label="CC (optional)" htmlFor="send-cc" error={ccError} hint="Separate several addresses with commas">
            <input id="send-cc" className="input" value={cc} onChange={(e) => setCc(e.target.value)} aria-invalid={!!ccError} />
          </Field>
          <Field label="Subject" htmlFor="send-subject">
            <input id="send-subject" className="input" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
          </Field>
          <Field label="Message" htmlFor="send-body">
            <textarea id="send-body" className="textarea send__body" value={body} onChange={(e) => setBody(e.target.value)} />
          </Field>
          {needsConfirm && inc && (
            <div className="alert alert--warning">
              <strong>The RFQ is not complete.</strong>
              {inc.not_found.length > 0 && <div>Not found: {inc.not_found.join(", ")}</div>}
              {missingCount > 0 && <div>{missingCount} fields are still blank across {Object.keys(inc.missing).length} products.</div>}
              {inc.suspicious > 0 && <div>{inc.suspicious} values are flagged to check.</div>}
              <label className="check send__confirm">
                <input type="checkbox" checked={confirmIncomplete} onChange={(e) => setConfirmIncomplete(e.target.checked)} /> Send anyway; the Summary sheet tells the recipient what is open
              </label>
            </div>
          )}
          {alreadySent && (
            <label className="check">
              <input type="checkbox" checked={resend} onChange={(e) => setResend(e.target.checked)} /> This version was already sent. Send it again.
            </label>
          )}
        </>
      ) : (
        <dl className="send__summary">
          <dt>To</dt>
          <dd>{to.trim()}</dd>
          {ccList.length > 0 && (
            <>
              <dt>CC</dt>
              <dd>{ccList.join(", ")}</dd>
            </>
          )}
          <dt>Subject</dt>
          <dd>{subject}</dd>
          <dt>Attachment</dt>
          <dd className="mono">{fileName}</dd>
          <dt>Contents</dt>
          <dd>
            {job.found} of {job.requested} products found · fill rate {pct(sheet.data?.report?.fill_overall ?? job.fill_rate)}
          </dd>
          <dt>From</dt>
          <dd className="subtle">the RFQ bot mailbox, as a reply in the original thread</dd>
        </dl>
      )}
    </Modal>
  );
}
