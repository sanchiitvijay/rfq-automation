import {
  CellStyleModule,
  ClientSideRowModelModule,
  CustomEditorModule,
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
  type CellFocusedEvent,
  type CellValueChangedEvent,
  type ColDef,
  type GetRowIdParams,
  type GridApi,
  type GridReadyEvent,
  type IRowNode,
  type RowClassRules,
  type SelectionChangedEvent,
  type ICellRendererParams,
  type TooltipCallbackParams,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useMarkReviewed, usePatchSheet, useRecheck, useSheet } from "../../api/hooks";
import type { CellEdit, Flag, JobStatus, SheetRow } from "../../api/types";
import { Badge, Button, EmptyState, Field, Menu, Modal, useToast } from "../../components/ui";
import { pct } from "../../lib/format";
import { SOURCE_TYPE_LABEL, SourceLink, isSafeUrl, primaryPicture } from "../jobs/sources";
import { tokens } from "../../theme/tokens";
import { ChoiceEditor } from "./ChoiceEditor";
import "./review.css";

// Only the grid features this editor uses (keeps the bundle small).
ModuleRegistry.registerModules([
  ClientSideRowModelModule,
  TextEditorModule,
  LargeTextEditorModule,
  CustomEditorModule,
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
  spacing: 5,
  rowHeight: 32, // = ROW_HEIGHT
  headerHeight: 34, // = HEADER_HEIGHT
});

const READ_ONLY = new Set(["product_id", "Lookup Status"]);
// Grid options must keep the same identity between renders: a new object makes the grid rebuild the
// checkbox column, which re-renders every row and swallows the second click of a double-click.
const ROW_SELECTION = { mode: "multiRow", checkboxes: true, headerCheckbox: true, enableClickSelection: false, selectAll: "filtered" } as const;
const SELECTION_COLUMN = { pinned: "left", width: 40, suppressHeaderMenuButton: true } as const;
// dropdown editors and tooltips open over the page, not inside the (short) grid where they'd be cut off
const POPUP_PARENT = typeof document !== "undefined" ? document.body : null;
const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 34;
const SAVE_DELAY_MS = 800;
const UNITS: Record<string, string> = { Length: "ft", Width: "in", Thickness: "mil", Weight: "lb" };

type GridRow = Record<string, string> & { __pid: string };
type View = "all" | "issues" | "missing" | "suspicious" | "not_found" | "edited";
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
  const [view, setView] = useState<View>("all");
  const [save, setSave] = useState<SaveState>("saved");
  const [errors, setErrors] = useState<{ product_id: string; column: string; error: string }[]>([]);
  const [removing, setRemoving] = useState<string[] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
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

  const options = data?.options;
  const canEdit = !locked;

  const columnDefs = useMemo<ColDef<GridRow>[]>(() => {
    const cols = data?.columns ?? [];
    const defs = cols.map((col) => {
      const opt = options?.[col];
      const hasList = !!(opt?.choices?.length || opt?.suggestions?.length);
      const def: ColDef<GridRow> = {
        field: col,
        headerName: UNITS[col] ? `${col} (${UNITS[col]})` : col,
        headerTooltip: opt?.choices?.length ? `Pick: ${opt.choices.join(" / ")}` : hasList ? "Type or pick a value already in use" : undefined,
        editable: (p) => !READ_ONLY.has(col) && canEdit && !!p.data,
        pinned: col === "product_id" ? "left" : undefined,
        width: col === "product_id" ? 120 : col === "Description" ? 280 : col === "Product details" ? 300 : col === "Lookup Status" ? 110 : 140,
        cellClassRules: {
          "cell--missing": (p) => !!p.data && flagMap.get(`${p.data.__pid}|${col}`)?.some((f) => f.type === "missing") === true,
          "cell--suspicious": (p) => !!p.data && flagMap.get(`${p.data.__pid}|${col}`)?.some((f) => f.type === "suspicious") === true,
          "cell--manual": (p) => !!p.data && rowsById.get(p.data.__pid)?.cells[col]?.source_type === "manual_edit",
          "cell--readonly": () => READ_ONLY.has(col),
          "cell--choice": () => hasList && canEdit,
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
      if (hasList) {
        def.cellEditor = ChoiceEditor;
        def.cellEditorPopup = true;
        def.cellEditorPopupPosition = "under";
        def.cellEditorParams = { choices: opt?.choices, suggestions: opt?.suggestions, unit: UNITS[col] };
      }
      if (col === "Image") {
        def.hide = true; // the Excel's Image cell follows Picture, so the grid shows one picture column
      }
      if (col === "Picture") {
        def.headerName = "Picture";
        def.width = 210;
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
    defs.push({
      colId: "__actions",
      headerName: "",
      pinned: "right",
      width: 48,
      resizable: false,
      sortable: false,
      suppressMovable: true,
      cellClass: "cell--actions",
      cellRenderer: (p: ICellRendererParams<GridRow>) =>
        p.data ? (
          <RowActions
            row={rowsById.get(p.data.__pid)}
            disabled={!canEdit}
            onRemove={() => setRemoving([p.data!.__pid])}
          />
        ) : null,
    });
    return defs;
  }, [data?.columns, options, flagMap, rowsById, canEdit]);

  const counts = useMemo(() => {
    const flags = data?.flags ?? [];
    const rows = data?.rows ?? [];
    const has = (pid: string, t: string) => flags.some((f) => f.product_id === pid && f.type === t);
    return {
      all: rows.length,
      issues: rows.filter((r) => r.lookup_status === "Not found" || flags.some((f) => f.product_id === r.product_id)).length,
      missing: rows.filter((r) => has(r.product_id, "missing")).length,
      suspicious: rows.filter((r) => has(r.product_id, "suspicious")).length,
      not_found: rows.filter((r) => r.lookup_status === "Not found").length,
      edited: rows.filter((r) => Object.values(r.cells).some((c) => c.source_type === "manual_edit")).length,
    } satisfies Record<View, number>;
  }, [data?.flags, data?.rows]);

  const passes = useCallback(
    (row: GridRow) => {
      const r = rowsById.get(row.__pid);
      if (!r) return false;
      const flags = (data?.flags ?? []).filter((f) => f.product_id === r.product_id);
      switch (view) {
        case "issues":
          return r.lookup_status === "Not found" || flags.length > 0;
        case "missing":
        case "suspicious":
          return flags.some((f) => f.type === view);
        case "not_found":
          return r.lookup_status === "Not found";
        case "edited":
          return Object.values(r.cells).some((c) => c.source_type === "manual_edit");
        default:
          return true;
      }
    },
    [data?.flags, rowsById, view],
  );

  useEffect(() => {
    gridRef.current?.onFilterChanged();
  }, [passes]);

  // rows that disappear (removed, or by someone else) must not stay "selected" behind the scenes
  useEffect(() => {
    setSelectedIds((ids) => ids.filter((id) => rowsById.has(id)));
  }, [rowsById]);

  // Every prop handed to the grid keeps its identity between renders (useCallback/useMemo): a new
  // function or object makes the grid refresh its rows, which swallows the second click of a double-click.
  const getRowId = useCallback((p: GetRowIdParams<GridRow>) => p.data.__pid, []);
  const onGridReady = useCallback((e: GridReadyEvent<GridRow>) => {
    gridRef.current = e.api;
  }, []);
  const viewRef = useRef(view);
  viewRef.current = view;
  const passesRef = useRef(passes);
  passesRef.current = passes;
  const isFilterPresent = useCallback(() => viewRef.current !== "all", []);
  const doesFilterPass = useCallback((node: IRowNode<GridRow>) => !!node.data && passesRef.current(node.data), []);
  const rowClassRules = useMemo<RowClassRules<GridRow>>(
    () => ({ "row--notfound": (p) => !!p.data && rowsById.get(p.data.__pid)?.lookup_status === "Not found" }),
    [rowsById],
  );
  const onSelectionChanged = useCallback((e: SelectionChangedEvent<GridRow>) => setSelectedIds(e.api.getSelectedRows().map((r) => r.__pid)), []);
  const onCellFocused = useCallback((e: CellFocusedEvent<GridRow>) => {
    const col = typeof e.column === "object" && e.column ? e.column.getColId() : null;
    const node = e.rowIndex !== null && e.rowIndex !== undefined ? e.api.getDisplayedRowAtIndex(e.rowIndex) : null;
    if (col && !col.startsWith("__") && col !== "ag-Grid-SelectionColumn" && node?.data) setFocused({ pid: node.data.__pid, col });
  }, []);

  const startRecheck = () => {
    gridRef.current?.stopEditing();
    setRecheckVersion(data?.version ?? null);
    recheck.mutate(undefined, {
      onError: (e) => toast(e.message, "error"),
      onSuccess: (d) => toast(`AI re-check done for version ${d.version}: ${d.report?.llm_status ?? ""}`, "success"),
    });
  };

  const removeRows = (ids: string[]) => {
    gridRef.current?.stopEditing();
    patch.mutate(
      { version: versionRef.current, edits: [], remove_rows: ids.map((product_id) => ({ product_id, reason: removeReason.trim() })) },
      {
        onSuccess: (next) => {
          versionRef.current = next.version;
          setRemoving(null);
          setRemoveReason("");
          gridRef.current?.deselectAll();
          toast(ids.length === 1 ? `${ids[0]} removed` : `${ids.length} rows removed`, "success");
        },
        onError: (e) =>
          toast(e instanceof ApiError && e.status === 409 ? "Someone else changed this RFQ; the latest version is loaded. Try again." : e.message, "error"),
      },
    );
  };

  if (sheet.isLoading) return <p className="muted">Loading the RFQ…</p>;
  if (sheet.isError) return <div className="alert alert--error">{sheet.error.message}</div>;
  if (!data || data.rows.length === 0) return <EmptyState title="No products to review">The email had no product IDs, or every row was removed.</EmptyState>;

  const inc = data.incomplete;
  const missingCount = Object.values(inc.missing).reduce((n, cols) => n + cols.length, 0);
  const saveLabel = { saved: `Saved · v${data.version}`, pending: "Unsaved changes…", saving: "Saving…", error: "Last change not saved" }[save];
  const viewLabels: Record<View, string> = {
    all: "All rows",
    issues: "Rows with issues",
    missing: "Missing values",
    suspicious: "Values to check",
    not_found: "Not found",
    edited: "Edited by hand",
  };
  const removeAll = removing !== null && removing.length >= data.rows.length;

  return (
    <div className="review">
      <div className="review__bar">
        <div className="review__stats">
          <span className="review__fill">
            Fill <strong className="num">{pct(data.report?.fill_overall)}</strong>
          </span>
          <Badge tone="danger">{inc.not_found.length} not found</Badge>
          <Badge tone="missing">{missingCount} missing</Badge>
          <Badge tone="suspicious">{inc.suspicious} to check</Badge>
          <span className={`save save--${save}`} aria-live="polite">
            {saveLabel}
          </span>
        </div>
        <div className="review__actions">
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
      <div className="review__tools">
        <div className="review__show">
          <label className="field__label" htmlFor="grid-view">Show</label>
          <select id="grid-view" className="input input--sm" value={view} onChange={(e) => setView(e.target.value as View)}>
            {(Object.keys(viewLabels) as View[]).map((v) => (
              <option key={v} value={v} disabled={v !== "all" && counts[v] === 0}>
                {viewLabels[v]} ({counts[v]})
              </option>
            ))}
          </select>
        </div>
        <div className="review__note">
          <label className="field__label" htmlFor="edit-note">Source for your edits</label>
          <input id="edit-note" className="input input--sm" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300}
                 placeholder="e.g. Supplier quote 16 Oct (saved on the Sources sheet)" />
        </div>
        <Menu
          label="More"
          size="sm"
          variant="ghost"
          width={280}
          sections={[
            {
              items: [
                { key: "import", label: "Upload edited file…", description: ".xlsx, .xls or .csv; checked before anything changes", disabled: locked, onSelect: onImport },
                {
                  key: "remove-sel",
                  label: selectedIds.length ? `Remove ${selectedIds.length} selected row${selectedIds.length > 1 ? "s" : ""}…` : "Remove selected rows…",
                  description: selectedIds.length ? undefined : "Tick rows on the left first",
                  danger: true,
                  disabled: !selectedIds.length || locked,
                  onSelect: () => setRemoving(selectedIds),
                },
              ],
            },
          ]}
        />
      </div>
      {recheck.isPending && (
        <div className="alert alert--info" role="status">
          The AI is re-checking version {recheckVersion ?? data.version}. Editing is paused until it finishes (usually 5–20 s), so
          the results always match what you see.
        </div>
      )}
      {errors.length > 0 && (
        <div className="alert alert--error">
          {errors.map((e, i) => (
            <div key={i}>
              <span className="mono">{e.product_id}</span> · {e.column}: {e.error}
            </div>
          ))}
        </div>
      )}
      {selectedIds.length > 0 && (
        <div className="review__selection" role="status">
          <strong>{selectedIds.length}</strong> selected
          <Button size="sm" variant="danger" disabled={locked} onClick={() => setRemoving(selectedIds)}>
            Remove {selectedIds.length === 1 ? "row" : `${selectedIds.length} rows`}…
          </Button>
          <Button size="sm" variant="ghost" onClick={() => gridRef.current?.deselectAll()}>
            Clear selection
          </Button>
        </div>
      )}
      {/* as tall as its rows (plus a horizontal scrollbar), capped by the CSS max-height for long RFQs */}
      <div className="review__grid" style={{ height: HEADER_HEIGHT + Math.max(data.rows.length, 3) * ROW_HEIGHT + 20 }}>
        <AgGridReact<GridRow>
          theme={theme}
          rowData={rowData}
          columnDefs={columnDefs}
          getRowId={getRowId}
          onGridReady={onGridReady}
          onCellValueChanged={onCellValueChanged}
          isExternalFilterPresent={isFilterPresent}
          doesExternalFilterPass={doesFilterPass}
          rowClassRules={rowClassRules}
          undoRedoCellEditing
          stopEditingWhenCellsLoseFocus
          tooltipShowDelay={300}
          enableCellTextSelection
          rowSelection={ROW_SELECTION}
          selectionColumnDef={SELECTION_COLUMN}
          onSelectionChanged={onSelectionChanged}
          onCellFocused={onCellFocused}
          popupParent={POPUP_PARENT}
          domLayout="normal"
        />
      </div>
      <div className="review__foot">
        <CellInspector focused={focused} rowsById={rowsById} flagMap={flagMap} />
        <div className="review__legend subtle">
          <span><i className="swatch swatch--missing" /> missing</span>
          <span><i className="swatch swatch--suspicious" /> check</span>
          <span><i className="swatch swatch--manual" /> edited</span>
          <span title="Double-click a cell (or press Enter) to edit; columns with a list open a dropdown. Ctrl+Z undoes. The ⋯ button at the end of a row removes it.">
            Double-click to edit · ⋯ row menu
          </span>
        </div>
      </div>
      {removing && (
        <Modal
          title={removing.length === 1 ? `Remove ${removing[0]} from the RFQ` : `Remove ${removing.length} rows from the RFQ`}
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRemoving(null)}>
                Cancel
              </Button>
              <Button variant="danger" disabled={removeReason.trim().length < 3 || locked} busy={patch.isPending} busyLabel="Removing…"
                      onClick={() => removeRows(removing)}>
                {removing.length === 1 ? "Remove row" : `Remove ${removing.length} rows`}
              </Button>
            </>
          }
        >
          {removing.length > 1 && (
            <p className="remove-list">
              {removing.map((id) => (
                <span key={id} className="mono">{id}</span>
              ))}
            </p>
          )}
          {removeAll && <div className="alert alert--warning">This removes every product: the RFQ will be empty.</div>}
          <p className="subtle">
            The whole row leaves the RFQ sheet (all its values and sources). The product ID and your reason stay on the Notes sheet
            and in the activity log, so nothing disappears silently.
          </p>
          <Field label="Reason (required)" htmlFor="rm-reason" hint="For example: customer dropped the item, duplicate of another line.">
            <input id="rm-reason" className="input" value={removeReason} onChange={(e) => setRemoveReason(e.target.value)} maxLength={300}
                   onKeyDown={(e) => e.key === "Enter" && removeReason.trim().length >= 3 && !patch.isPending && removeRows(removing)} />
          </Field>
        </Modal>
      )}
    </div>
  );
}

interface RowActionsProps {
  row: SheetRow | undefined;
  disabled: boolean;
  onRemove: () => void;
}

/** The ⋯ menu at the end of every row. */
function RowActions({ row, disabled, onRemove }: RowActionsProps) {
  if (!row) return null;
  const page = row.supplier["Product page"]?.value || Object.values(row.cells).find((c) => c.url?.includes("ferguson.com/product"))?.url;
  const spec = row.supplier["Spec sheet"]?.value;
  return (
    <Menu
      variant="icon"
      ariaLabel={`Actions for ${row.product_id}`}
      label={<DotsIcon />}
      width={230}
      sections={[
        {
          title: row.product_id,
          items: [
            ...(isSafeUrl(page) ? [{ key: "page", label: "Open product page", href: page, title: page }] : []),
            ...(isSafeUrl(spec) ? [{ key: "spec", label: "Open spec sheet", href: spec, title: spec }] : []),
            { key: "remove", label: "Remove row…", description: "Kept on the Notes sheet with your reason", danger: true, disabled, onSelect: onRemove },
          ],
        },
      ]}
    />
  );
}

function DotsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="3" cy="8" r="1.5" fill="currentColor" />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
      <circle cx="13" cy="8" r="1.5" fill="currentColor" />
    </svg>
  );
}

interface InspectorProps {
  focused: { pid: string; col: string } | null;
  rowsById: Map<string, SheetRow>;
  flagMap: Map<string, Flag[]>;
}

/** Shows where the selected cell's value came from, with a working link to that page or PDF. */
function CellInspector({ focused, rowsById, flagMap }: InspectorProps) {
  const row = focused ? rowsById.get(focused.pid) : undefined;
  if (!focused || !row) return <div className="inspector subtle">Click a cell to see its source and link.</div>;
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
