import {
  CellStyleModule,
  ClientSideRowModelModule,
  ExternalFilterModule,
  LargeTextEditorModule,
  ModuleRegistry,
  RowApiModule,
  RowSelectionModule,
  RowStyleModule,
  TextEditorModule,
  TooltipModule,
  UndoRedoEditModule,
  ValidationModule,
  themeQuartz,
  type CellValueChangedEvent,
  type ColDef,
  type GridApi,
  type TooltipCallbackParams,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useMarkReviewed, usePatchSheet, useRecheck, useSheet } from "../../api/hooks";
import type { CellEdit, Flag, JobStatus, SheetRow } from "../../api/types";
import { Badge, Button, EmptyState, Field, Modal, useToast } from "../../components/ui";
import { pct } from "../../lib/format";
import { SOURCE_TYPE_LABEL, SourceLink, primaryPicture } from "../jobs/sources";
import { tokens } from "../../theme/tokens";
import "./review.css";

// Only the grid features this editor uses (keeps the bundle small).
ModuleRegistry.registerModules([
  ClientSideRowModelModule,
  TextEditorModule,
  LargeTextEditorModule,
  UndoRedoEditModule,
  CellStyleModule,
  RowStyleModule,
  TooltipModule,
  ExternalFilterModule,
  RowSelectionModule,
  RowApiModule,
  ...(import.meta.env.DEV ? [ValidationModule] : []), // readable warnings while developing
]);

const theme = themeQuartz.withParams({
  accentColor: tokens.primary,
  foregroundColor: tokens.ink,
  backgroundColor: tokens.surface,
  headerBackgroundColor: tokens.surfaceAlt,
  borderColor: tokens.border,
  fontFamily: tokens.fontSans,
  fontSize: 13,
  headerFontWeight: 600,
  borderRadius: 2,
  wrapperBorderRadius: 3,
  spacing: 6,
  rowHeight: 34,
  headerHeight: 36,
});

const READ_ONLY = new Set(["product_id", "Lookup Status"]);
const SAVE_DELAY_MS = 800;
const UNITS: Record<string, string> = { Length: "ft", Width: "in", Thickness: "mil", Weight: "lb" };

type GridRow = Record<string, string> & { __pid: string };
type SaveState = "saved" | "pending" | "saving" | "error";

function toGridRows(rows: SheetRow[]): GridRow[] {
  return rows.map((r) => {
    const out: GridRow = { __pid: r.product_id, product_id: r.product_id, "Lookup Status": r.lookup_status };
    for (const [col, cell] of Object.entries(r.cells)) out[col] = cell.value;
    return out;
  });
}

interface Props {
  jobId: string;
  status: JobStatus;
  /** "by Asha (version 3)" from the latest Reviewed event, when the RFQ is reviewed */
  reviewedBy?: string;
  onImport: () => void;
}

/** Excel-like editor for the RFQ sheet. Edits autosave in small batches; the server re-runs the checks. */
export default function ReviewGrid({ jobId, status, reviewedBy, onImport }: Props) {
  const sheet = useSheet(jobId, true);
  const patch = usePatchSheet(jobId);
  const recheck = useRecheck(jobId);
  const review = useMarkReviewed(jobId);
  const toast = useToast();
  const gridRef = useRef<GridApi<GridRow> | null>(null);
  const pending = useRef(new Map<string, CellEdit>());
  const timer = useRef<number | undefined>(undefined);
  const [note, setNote] = useState("");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [save, setSave] = useState<SaveState>("saved");
  const [errors, setErrors] = useState<{ product_id: string; column: string; error: string }[]>([]);
  const [removing, setRemoving] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focused, setFocused] = useState<{ pid: string; col: string } | null>(null);
  const [recheckVersion, setRecheckVersion] = useState<number | null>(null);
  const locked = recheck.isPending || status === "sending";
  const [removeReason, setRemoveReason] = useState("");

  const data = sheet.data;
  const flagMap = useMemo(() => {
    const m = new Map<string, Flag[]>();
    for (const f of data?.flags ?? []) {
      const key = `${f.product_id}|${f.column}`;
      m.set(key, [...(m.get(key) ?? []), f]);
    }
    return m;
  }, [data?.flags]);
  const rowsById = useMemo(() => new Map((data?.rows ?? []).map((r) => [r.product_id, r])), [data?.rows]);
  const rowData = useMemo(() => toGridRows(data?.rows ?? []), [data?.rows]);

  const versionRef = useRef(0);
  const inFlight = useRef(false);
  useEffect(() => {
    if (data) versionRef.current = data.version;
  }, [data]);

  const flushRef = useRef<() => void>(() => undefined);
  flushRef.current = () => {
    window.clearTimeout(timer.current);
    if (pending.current.size === 0) return;
    if (inFlight.current) {
      // one save at a time, always against the newest version
      timer.current = window.setTimeout(() => flushRef.current(), 300);
      return;
    }
    const edits = [...pending.current.values()];
    pending.current.clear();
    inFlight.current = true;
    setSave("saving");
    patch.mutate(
      { version: versionRef.current, edits },
      {
        onSuccess: (next) => {
          versionRef.current = next.version;
          setSave(pending.current.size ? "pending" : "saved");
          setErrors([]);
        },
        onError: (e) => {
          setSave("error");
          if (e instanceof ApiError && e.status === 409) {
            toast("Someone else changed this RFQ. The latest version was loaded; please redo your last edit.", "error");
          } else if (e instanceof ApiError && e.status === 422) {
            const body = e.body as { errors?: { product_id: string; column: string; error: string }[] };
            setErrors(body.errors ?? []);
            toast("Some values were not saved. See the messages above the grid.", "error");
          } else {
            toast(e.message, "error");
          }
          // put the server's values back into the edited rows (a refetch alone returns the same
          // objects when nothing changed on the server, so the grid would keep showing the bad value)
          const restore = (rows: SheetRow[]) => {
            const byId = new Map(rows.map((r) => [r.product_id, r]));
            for (const pid of new Set(edits.map((x) => x.product_id))) {
              const row = byId.get(pid);
              const node = gridRef.current?.getRowNode(pid);
              if (row && node) node.setData(toGridRows([row])[0]!);
            }
          };
          void sheet.refetch().then((r) => r.data && restore(r.data.rows));
        },
        onSettled: () => {
          inFlight.current = false;
        },
      },
    );
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onCellValueChanged = useCallback(
    (e: CellValueChangedEvent<GridRow>) => {
      const column = e.colDef.field;
      if (!column || !e.data) return;
      const value = e.newValue === null || e.newValue === undefined ? "" : String(e.newValue);
      pending.current.set(`${e.data.__pid}|${column}`, { product_id: e.data.__pid, column, value, note });
      setSave("pending");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => flushRef.current(), SAVE_DELAY_MS);
    },
    [note],
  );

  const columnDefs = useMemo<ColDef<GridRow>[]>(() => {
    const cols = data?.columns ?? [];
    return cols.map((col) => {
      const def: ColDef<GridRow> = {
        field: col,
        headerName: UNITS[col] ? `${col} (${UNITS[col]})` : col,
        editable: (p) => !READ_ONLY.has(col) && !locked && !!p.data,
        pinned: col === "product_id" ? "left" : undefined,
        width: col === "product_id" ? 130 : col === "Description" ? 300 : col === "Product details" ? 320 : col === "Lookup Status" ? 120 : 150,
        cellClassRules: {
          "cell--missing": (p) => !!p.data && flagMap.get(`${p.data.__pid}|${col}`)?.some((f) => f.type === "missing") === true,
          "cell--suspicious": (p) => !!p.data && flagMap.get(`${p.data.__pid}|${col}`)?.some((f) => f.type === "suspicious") === true,
          "cell--manual": (p) => !!p.data && rowsById.get(p.data.__pid)?.cells[col]?.source_type === "manual_edit",
          "cell--readonly": () => READ_ONLY.has(col),
        },
        tooltip: (p: TooltipCallbackParams<GridRow>) => {
          if (!p.data) return "";
          const row = rowsById.get(p.data.__pid);
          const cell = row?.cells[col];
          const flags = flagMap.get(`${p.data.__pid}|${col}`) ?? [];
          const lines = flags.map((f) => `${f.type === "missing" ? "Missing" : "Check"} (${f.check === "llm" ? "AI" : "rule"}): ${f.reason}`);
          if (cell) lines.push(`Source: ${cell.source_type} (${cell.confidence}) · ${cell.source}`);
          if (cell?.url) lines.push(`Link: ${cell.url} (click the cell to open it below)`);
          if (col === "product_id" && row?.lookup_status === "Not found") lines.push(row.not_found_reason);
          return lines.join("\n");
        },
      };
      if (col === "Image") {
        def.hide = true; // the Excel's Image cell follows Picture, so the grid shows one picture column
      }
      if (col === "Picture") {
        def.headerName = "Picture";
        def.width = 230;
        def.cellRenderer = (p: { value?: string }) =>
          p.value ? (
            <span className="pic-cell">
              {(() => {
                const shown = primaryPicture(p.value);
                return shown ? <img src={`${shown}${shown.includes("?") ? "&" : "?"}fmt=jpg&w=60`} alt="" loading="lazy" /> : null;
              })()}
              <span className="pic-cell__url">{p.value}</span>
            </span>
          ) : null;
      }
      if (col === "Lookup Status") {
        def.cellRenderer = (p: { value: string }) => (
          <Badge tone={p.value === "Not found" ? "danger" : p.value === "Manual" ? "info" : "success"}>{p.value}</Badge>
        );
      }
      if (col === "Product details") {
        def.cellEditor = "agLargeTextCellEditor";
        def.cellEditorPopup = true;
        def.cellEditorParams = { maxLength: 2000 };
      }
      return def;
    });
  }, [data?.columns, flagMap, rowsById, locked]);

  const hasIssues = useCallback(
    (row: GridRow) => {
      const r = rowsById.get(row.__pid);
      if (!r) return false;
      if (r.lookup_status === "Not found") return true;
      return (data?.flags ?? []).some((f) => f.product_id === r.product_id);
    },
    [data?.flags, rowsById],
  );

  useEffect(() => {
    gridRef.current?.onFilterChanged();
  }, [onlyIssues, hasIssues]);

  const startRecheck = () => {
    gridRef.current?.stopEditing();
    setRecheckVersion(data?.version ?? null);
    recheck.mutate(undefined, {
      onError: (e) => toast(e.message, "error"),
      onSuccess: (d) => toast(`AI re-check done for version ${d.version}: ${d.report?.llm_status ?? ""}`, "success"),
    });
  };

  if (sheet.isLoading) return <p className="muted">Loading the RFQ…</p>;
  if (sheet.isError) return <div className="alert alert--error">{sheet.error.message}</div>;
  if (!data || data.rows.length === 0) return <EmptyState title="No products to review">The email had no product IDs.</EmptyState>;

  const inc = data.incomplete;
  const missingCount = Object.values(inc.missing).reduce((n, cols) => n + cols.length, 0);
  const saveLabel = { saved: `Saved · version ${data.version}`, pending: "Unsaved changes…", saving: "Saving…", error: "Last change was not saved" }[save];

  return (
    <div className="review">
      <div className="review__bar">
        <div className="review__stats">
          <span>
            Fill rate <strong className="num">{pct(data.report?.fill_overall)}</strong>
          </span>
          <Badge tone="danger">{inc.not_found.length} not found</Badge>
          <Badge tone="missing">{missingCount} missing</Badge>
          <Badge tone="suspicious">{inc.suspicious} to check</Badge>
          <span className={`save save--${save}`} aria-live="polite">
            {saveLabel}
          </span>
        </div>
        <div className="review__actions">
          <label className="check">
            <input type="checkbox" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} /> Only rows with issues
          </label>
          <Button size="sm" variant="ghost" disabled={locked} onClick={onImport} title="Upload a copy you edited in Excel">
            Upload edited Excel
          </Button>
          <Button
            size="sm"
            variant="ghost"
            busy={recheck.isPending}
            busyLabel="AI checking…"
            disabled={save !== "saved" || status === "sending"}
            title={save !== "saved" ? "Wait until your last change is saved" : "Run the AI contradiction check again on the current version"}
            onClick={startRecheck}
          >
            Re-check with AI
          </Button>
          <ReviewControl
            status={status}
            reviewedBy={reviewedBy}
            busy={review.isPending}
            disabled={locked || save !== "saved"}
            onChange={(done) =>
              review.mutate(
                { done, version: data.version },
                { onError: (e) => toast(e.message, "error"), onSuccess: () => toast(done ? `Version ${data.version} marked as reviewed` : "Review reopened", "success") },
              )
            }
          />
        </div>
      </div>
      {recheck.isPending && (
        <div className="alert alert--info" role="status">
          The AI is re-checking version {recheckVersion ?? data.version}. Editing is paused until it finishes (usually 5–20 s), so
          the results always match what you see.
        </div>
      )}
      <div className="review__note">
        <Field label="Source for your edits" htmlFor="edit-note" hint="Saved with every value you type, e.g. 'Supplier quote 16 Oct' or 'Manufacturer spec sheet'. It appears on the Sources sheet.">
          <input id="edit-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Where does the value come from?" maxLength={300} />
        </Field>
      </div>
      {errors.length > 0 && (
        <div className="alert alert--error">
          {errors.map((e, i) => (
            <div key={i}>
              <span className="mono">{e.product_id}</span> · {e.column}: {e.error}
            </div>
          ))}
        </div>
      )}
      <div className="review__legend subtle">
        <span><i className="swatch swatch--missing" /> missing</span>
        <span><i className="swatch swatch--suspicious" /> check this value</span>
        <span><i className="swatch swatch--manual" /> edited by hand</span>
        <span>Hover a cell for its source and the reason it was flagged. Double-click to edit; Ctrl+Z undoes.</span>
      </div>
      <div className="review__grid">
        <AgGridReact<GridRow>
          theme={theme}
          rowData={rowData}
          columnDefs={columnDefs}
          getRowId={(p) => p.data.__pid}
          onGridReady={(e) => (gridRef.current = e.api)}
          onCellValueChanged={onCellValueChanged}
          isExternalFilterPresent={() => onlyIssues}
          doesExternalFilterPass={(node) => !!node.data && hasIssues(node.data)}
          rowClassRules={{ "row--notfound": (p) => !!p.data && rowsById.get(p.data.__pid)?.lookup_status === "Not found" }}
          undoRedoCellEditing
          stopEditingWhenCellsLoseFocus
          tooltipShowDelay={300}
          enableCellTextSelection
          rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
          onSelectionChanged={(e) => setSelectedId(e.api.getSelectedRows()[0]?.__pid ?? null)}
          onCellFocused={(e) => {
            const col = typeof e.column === "object" && e.column ? e.column.getColId() : null;
            const node = e.rowIndex !== null && e.rowIndex !== undefined ? e.api.getDisplayedRowAtIndex(e.rowIndex) : null;
            if (col && node?.data) setFocused({ pid: node.data.__pid, col });
          }}
          domLayout="normal"
        />
      </div>
      <CellInspector focused={focused} rowsById={rowsById} flagMap={flagMap} />
      <div className="review__foot">
        <Button size="sm" variant="danger" disabled={!selectedId || status === "sending"} onClick={() => setRemoving(selectedId)}>
          Remove selected row…
        </Button>
        <span className="subtle">Removed rows stay listed on the Notes sheet with your reason.</span>
      </div>
      {removing && (
        <Modal
          title={`Remove ${removing} from the RFQ`}
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRemoving(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={removeReason.trim().length < 3}
                busy={patch.isPending}
                onClick={() =>
                  patch.mutate(
                    { version: data.version, edits: [], remove_rows: [{ product_id: removing, reason: removeReason.trim() }] },
                    {
                      onSuccess: () => {
                        setRemoving(null);
                        setRemoveReason("");
                        toast(`${removing} removed`, "success");
                      },
                      onError: (e) => toast(e.message, "error"),
                    },
                  )
                }
              >
                Remove row
              </Button>
            </>
          }
        >
          <Field label="Reason (required)" htmlFor="rm-reason" hint="For example: customer dropped the item, duplicate of another line.">
            <input id="rm-reason" className="input" value={removeReason} onChange={(e) => setRemoveReason(e.target.value)} maxLength={300} />
          </Field>
        </Modal>
      )}
    </div>
  );
}

interface InspectorProps {
  focused: { pid: string; col: string } | null;
  rowsById: Map<string, SheetRow>;
  flagMap: Map<string, Flag[]>;
}

/** Shows where the selected cell's value came from, with a working link to that page or PDF. */
function CellInspector({ focused, rowsById, flagMap }: InspectorProps) {
  if (!focused) return <div className="inspector subtle">Click a cell to see its source and link.</div>;
  const row = rowsById.get(focused.pid);
  const cell = row?.cells[focused.col];
  const flags = flagMap.get(`${focused.pid}|${focused.col}`) ?? [];
  return (
    <div className="inspector" aria-live="polite">
      <span className="mono">{focused.pid}</span> · <strong>{focused.col}</strong>
      {cell ? (
        <>
          <span className="inspector__value">{cell.value}</span>
          <span className="subtle">
            {SOURCE_TYPE_LABEL[cell.source_type] ?? cell.source_type} ({cell.confidence}) · {cell.source}
          </span>
          <SourceLink cell={cell} />
        </>
      ) : focused.col === "product_id" || focused.col === "Lookup Status" ? (
        <span className="subtle">{row?.lookup_status === "Not found" ? row.not_found_reason : row?.tried.join(" · ")}</span>
      ) : (
        <span className="subtle">Blank: no source had a value. Type one in, with its source in the note field above.</span>
      )}
      {flags.map((f) => (
        <Badge key={f.type + f.reason} tone={f.type === "missing" ? "missing" : "suspicious"}>
          {f.check === "llm" ? "AI" : "Rule"}: {f.reason}
        </Badge>
      ))}
    </div>
  );
}

interface ReviewControlProps {
  status: JobStatus;
  reviewedBy?: string;
  busy: boolean;
  disabled: boolean;
  onChange: (done: boolean) => void;
}

/** One place that says whether this version is reviewed, by whom, and offers the single next step. */
function ReviewControl({ status, reviewedBy, busy, disabled, onChange }: ReviewControlProps) {
  if (status === "ready") {
    return (
      <span className="review-state">
        <Badge tone="success">Reviewed{reviewedBy ? ` ${reviewedBy}` : ""}</Badge>
        <Button size="sm" variant="ghost" busy={busy} disabled={disabled} onClick={() => onChange(false)}>
          Reopen
        </Button>
      </span>
    );
  }
  if (status === "needs_review" || status === "sent") {
    return (
      <span className="review-state">
        <Badge tone="warning">{status === "sent" ? "Sent · changes since?" : "Needs review"}</Badge>
        <Button size="sm" variant="secondary" busy={busy} disabled={disabled || status === "sent"} onClick={() => onChange(true)}>
          Mark reviewed
        </Button>
      </span>
    );
  }
  return null;
}
