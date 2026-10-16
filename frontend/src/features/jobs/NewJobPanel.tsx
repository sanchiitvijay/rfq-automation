import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateFromText, useUploadEml } from "../../api/hooks";
import { Button, Card, Field, useToast } from "../../components/ui";

/** Paste an email body or upload a .eml (for emails that did not come through the Gmail extension). */
export function NewJobPanel({ onDone }: { onDone: () => void }) {
  const [subject, setSubject] = useState("");
  const [sender, setSender] = useState("");
  const [body, setBody] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const create = useCreateFromText();
  const upload = useUploadEml();
  const toast = useToast();
  const navigate = useNavigate();

  const go = (id: string) => {
    onDone();
    navigate(`/jobs/${id}`);
  };

  return (
    <Card title="New RFQ request" actions={<Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>}>
      <div className="new-job">
        <div className="new-job__paste">
          <div className="new-job__row">
            <Field label="Subject" htmlFor="nj-subject">
              <input id="nj-subject" className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="RFQ: detector tapes" />
            </Field>
            <Field label="From" htmlFor="nj-sender" hint="Used as the default recipient when sending">
              <input id="nj-sender" className="input" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="Priya Nair <priya@example.com>" />
            </Field>
          </div>
          <Field label="Email body" htmlFor="nj-body" hint="Paste the whole email; product IDs are found automatically">
            <textarea id="nj-body" className="textarea" value={body} onChange={(e) => setBody(e.target.value)} placeholder={"Hi team,\n\nPlease quote:\n5106912\n5106935"} />
          </Field>
          <div>
            <Button
              variant="primary"
              disabled={!body.trim()}
              busy={create.isPending}
              onClick={() =>
                create.mutate(
                  { subject, sender, body_text: body },
                  { onSuccess: (r) => go(r.job_id), onError: (e) => toast(e.message, "error") },
                )
              }
            >
              Start RFQ
            </Button>
          </div>
        </div>
        <div className="new-job__upload">
          <h4>Or upload the email</h4>
          <p className="subtle">A .eml file keeps Excel attachments. In Gmail: open the email → ⋮ → Download message.</p>
          <input
            ref={fileRef}
            type="file"
            accept=".eml,message/rfc822"
            className="visually-hidden"
            id="nj-file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file, { onSuccess: (r) => go(r.job_id), onError: (err) => toast(err.message, "error") });
              e.target.value = "";
            }}
          />
          <Button busy={upload.isPending} onClick={() => fileRef.current?.click()}>
            Choose .eml file
          </Button>
        </div>
      </div>
    </Card>
  );
}
