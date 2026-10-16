import { useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useExportFormats, useImportPreview, usePatchSheet } from "../../api/hooks";
import type { ImportChange, ImportPreview } from "../../api/types";
import { Badge, Button, Field, Modal, useToast } from "../../components/ui";
import "./import.css";

const STATUS: Record<ImportChange["status"], { tone: "success" | "danger" | "warning"; label: string }> = {
  ok: { tone: "success", label: "Ready" },
  invalid: { tone: "danger", label: "Invalid" },
  conflict: { tone: "warning", label: "Conflict" },
};

const keyOf = (c: ImportChange) => `${c.product_id}|${c.column}`;

/**
 * Upload an RFQ workbook that was edited in Excel. Step 1 checks the file and shows every change;
 * step 2 applies only the ticked, valid changes through the normal edit path (validated, versioned,
 * logged with "Uploaded Excel" as the source).
 */
export function ImportDialog({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const check = useImportPreview(jobId);
  const patch = usePatchSheet(jobId);
  const toast = useToast();
  const formats = useExportFormats();
  const accept = formats.data?.upload.accept ?? ".xlsx,.xlsm,.xls,.csv";
  const acceptLabel = formats.data?.upload.label ?? "Excel or CSV";
  const [result, setResult] = useState<ImportPreview | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const choose = (file: File) => {
    setError(null);
    check.mutate(file, {
      onSuccess: (p) => {
        setResult(p);
        setPicked(new Set(p.changes.filter((c) => c.status === "ok").map(keyOf))); // conflicts start unticked
      },
      onError: (e) => setError(e.message),
    });
  };

  const applicable = useMemo(() => (result?.changes ?? []).filter((c) => c.status !== "invalid"), [result]);
  const chosen = applicable.filter((c) => picked.has(keyOf(c)));

  const apply = () => {
    if (!result) return;
    const source = `Uploaded file '${result.filename}'${note.trim() ? `: ${note.trim()}` : ""}`;
    patch.mutate(
      {
        version: result.current_version,
        edits: chosen.map((c) => ({ product_id: c.product_id, column: c.column, value: c.uploaded, note: source })),
      },
      {
        onSuccess: (s) => {
          toast(`${chosen.length} changes applied from ${result.filename} (version ${s.version})`, "success");
          onClose();
        },
        onError: (e) =>
          setError(
            e instanceof ApiError && e.status === 409
              ? "The RFQ was changed while you were looking at the preview. Upload the file again to see the latest differences."
              : e.message,
          ),
      },
    );
  };

  const toggle = (c: ImportChange) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(keyOf(c))) next.delete(keyOf(c));
      else next.add(keyOf(c));
      return next;
    });

  return (
    <Modal
      title="Upload edited file"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {result?.ok && (
            <Button variant="primary" disabled={chosen.length === 0} busy={patch.isPending} busyLabel="Applying…" onClick={apply}>
              Apply {chosen.length} {chosen.length === 1 ? "change" : "changes"}
            </Button>
          )}
        </>
      }
    >
      <p className="muted">
        Upload the RFQ you downloaded and edited: {acceptLabel}. Nothing changes until you review the differences and
        click Apply. Only the RFQ sheet (or the CSV's single sheet) is read.
      </p>
      <div>
        <input
          ref={fileRef}
          type="file"
          accept={accept}
          className="visually-hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) choose(f);
            e.target.value = "";
          }}
        />
        <Button busy={check.isPending} busyLabel="Checking the file…" onClick={() => fileRef.current?.click()}>
          {result ? "Choose another file" : "Choose file"}
        </Button>
        {result && <span className="subtle"> {result.filename}{result.file_version ? ` · downloaded at version ${result.file_version}` : ""}</span>}
      </div>
      {error && <div className="alert alert--error">{error}</div>}
      {result && result.errors.length > 0 && (
        <div className="alert alert--error">
          <strong>This file can't be used:</strong>
          {result.errors.map((e) => (
            <div key={e}>{e}</div>
          ))}
        </div>
      )}
      {result && result.warnings.length > 0 && (
        <div className="alert alert--warning">
          {result.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      )}
      {result?.ok && result.changes.length === 0 && <div className="alert alert--info">No differences found: the file matches the RFQ.</div>}
      {result?.ok && result.changes.length > 0 && (
        <>
          <p className="subtle">
            {result.counts.ok} ready · {result.counts.conflict} conflicts (unticked) · {result.counts.invalid} invalid (not applied)
          </p>
          <div className="import__table">
            <table className="table">
              <thead>
                <tr>
                  <th aria-label="Apply" />
                  <th>Cell</th>
                  <th>Product</th>
                  <th>Column</th>
                  <th>Now in the app</th>
                  <th>In your file</th>
                  <th>Check</th>
                </tr>
              </thead>
              <tbody>
                {result.changes.map((c) => (
                  <tr key={keyOf(c)} className={c.status === "invalid" ? "import__row--invalid" : undefined}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Apply ${c.column} for ${c.product_id}`}
                        disabled={c.status === "invalid"}
                        checked={picked.has(keyOf(c))}
                        onChange={() => toggle(c)}
                      />
                    </td>
                    <td className="mono">{c.cell}</td>
                    <td className="mono">{c.product_id}</td>
                    <td>{c.column}</td>
                    <td className="import__value">{c.current || <span className="subtle">blank</span>}</td>
                    <td className="import__value">{c.uploaded || <span className="subtle">blank</span>}</td>
                    <td>
                      <Badge tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Badge>
                      {c.message && <div className="subtle">{c.message}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Field label="Source note (optional)" htmlFor="import-note" hint={`Saved with every applied value after "Uploaded file '${result.filename}'", e.g. "supplier quote 16 Oct".`}>
            <input id="import-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
          </Field>
        </>
      )}
    </Modal>
  );
}
