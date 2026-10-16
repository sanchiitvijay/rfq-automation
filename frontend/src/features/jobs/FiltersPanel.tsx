import { useEffect, useId, useState } from "react";
import { useFacets } from "../../api/hooks";
import type { JobFilters, Suggestion } from "../../api/types";
import { Badge, Button, Card, SearchBox } from "../../components/ui";
import { useDebounced } from "../../hooks/useDebounced";
import { useLabels } from "./useLabels";

interface Props {
  filters: JobFilters;
  set: (patch: Partial<JobFilters>) => void;
  clear: () => void;
  active: (keyof JobFilters)[];
}

const TEXT_FIELDS = ["subject", "sender", "product"] as const;
// filters behind "More filters" (the button shows how many of them are set)
const ADVANCED: (keyof JobFilters)[] = ["subject", "sender", "product", "source", "to"];

/** yyyy-mm-dd in the user's own time zone (what <input type="date"> uses). */
function localDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return localDate(d);
}
const FIXED_NAMES: Partial<Record<keyof JobFilters, string>> = {
  status: "Status", source: "Source", from: "Received from", to: "Received to",
};

function chipName(k: keyof JobFilters, field: (v: string) => string): string {
  return FIXED_NAMES[k] ?? field(k);
}

function chipValue(k: keyof JobFilters, v: string, labels: ReturnType<typeof useLabels>): string {
  if (k === "status") return labels.status(v);
  if (k === "source") return labels.source(v);
  return v;
}

/** A text filter that writes to the URL only after typing pauses. */
function useDraft(value: string, apply: (v: string) => void) {
  const [draft, setDraft] = useState(value);
  const debounced = useDebounced(draft, 350);
  useEffect(() => setDraft(value), [value]); // URL changed elsewhere (chip removed, header search…)
  useEffect(() => {
    if (debounced !== value) apply(debounced.trim());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  return [draft, setDraft] as const;
}

/** One field per filter. Options (statuses, sources, sorts, page sizes) come from the server. */
export function FiltersPanel({ filters, set, clear, active }: Props) {
  const facets = useFacets();
  const labels = useLabels();
  const uid = useId().replace(/:/g, "");
  const f = facets.data;
  const max = f?.max_text ?? 200;
  const [q, setQ] = useDraft(filters.q, (v) => set({ q: v }));
  const [subject, setSubject] = useDraft(filters.subject, (v) => set({ subject: v }));
  const [sender, setSender] = useDraft(filters.sender, (v) => set({ sender: v }));
  const [product, setProduct] = useDraft(filters.product, (v) => set({ product: v }));
  const drafts = { subject: [subject, setSubject], sender: [sender, setSender], product: [product, setProduct] } as const;
  const rangeError = filters.from && filters.to && filters.from > filters.to ? "'From' is after 'To'" : null;
  const placeholders: Record<(typeof TEXT_FIELDS)[number], string> = {
    subject: "e.g. detector tape",
    sender: "name or email address",
    product: "e.g. 5106912",
  };

  const pick = (s: Suggestion) => set({ [s.field]: s.value, q: "" } as Partial<JobFilters>);

  // "Received" dropdown: a preset when the dates match one exactly, otherwise "custom"
  const today = localDate(new Date());
  const presets = f?.date_presets ?? [];
  const preset = !filters.from && !filters.to ? "" : (!filters.to && presets.find((d) => filters.from === daysAgo(d.days))?.value) || "custom";
  const advancedActive = ADVANCED.filter((k) => filters[k]).length;
  const [advanced, setAdvanced] = useState(advancedActive > 0);
  useEffect(() => {
    if (advancedActive > 0 || preset === "custom") setAdvanced(true); // a filter set from elsewhere (link, header search) is shown
  }, [advancedActive, preset]);

  return (
    <Card className="filters">
      <div className="filters__top">
        <div className="filters__search">
          <SearchBox
            label="Search requests"
            value={q}
            maxLength={max}
            onChange={setQ}
            onSubmit={(text) => set({ q: text })}
            onPick={pick}
            placeholder="Search subject, sender, email text or product ID…"
          />
        </div>
        <label className="visually-hidden" htmlFor={`${uid}-status`}>Status</label>
        <select id={`${uid}-status`} className="input filters__select" value={filters.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Any status</option>
          {f?.statuses.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label} ({s.count ?? 0})
            </option>
          ))}
        </select>
        <label className="visually-hidden" htmlFor={`${uid}-received`}>Received</label>
        <select
          id={`${uid}-received`}
          className="input filters__select"
          value={preset}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "custom") {
              setAdvanced(true);
              if (!filters.from && !filters.to) set({ from: today });
              return;
            }
            const d = presets.find((x) => x.value === v);
            set({ from: d ? daysAgo(d.days) : "", to: "" });
          }}
        >
          <option value="">Any time</option>
          {presets.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
          <option value="custom">Custom dates…</option>
        </select>
        <label className="visually-hidden" htmlFor={`${uid}-sort`}>Sort</label>
        <select id={`${uid}-sort`} className="input filters__select" value={filters.sort || f?.sorts[0]?.value || ""} onChange={(e) => set({ sort: e.target.value })}>
          {f?.sorts.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <Button variant="ghost" aria-expanded={advanced} aria-controls={`${uid}-advanced`} onClick={() => setAdvanced((a) => !a)}>
          {advanced ? "Fewer filters" : `More filters${advancedActive ? ` (${advancedActive})` : ""}`}
        </Button>
      </div>
      {advanced && (
        <div className="filters__grid" id={`${uid}-advanced`}>
          {TEXT_FIELDS.map((key) => {
            const [value, setValue] = drafts[key];
            return (
              <div key={key} className="field">
                <label className="field__label" htmlFor={`${uid}-${key}`}>{labels.field(key)}</label>
                <input id={`${uid}-${key}`} className="input" value={value} maxLength={max} placeholder={placeholders[key]} onChange={(e) => setValue(e.target.value)} />
              </div>
            );
          })}
          <div className="field">
            <label className="field__label" htmlFor={`${uid}-source`}>Source</label>
            <select id={`${uid}-source`} className="input" value={filters.source} onChange={(e) => set({ source: e.target.value })}>
              <option value="">Any source</option>
              {f?.sources.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label} ({s.count ?? 0})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor={`${uid}-from`}>Received from</label>
            <input id={`${uid}-from`} className="input" type="date" value={filters.from} max={filters.to || undefined} aria-invalid={!!rangeError}
                   onChange={(e) => set({ from: e.target.value })} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor={`${uid}-to`}>Received to</label>
            <input id={`${uid}-to`} className="input" type="date" value={filters.to} min={filters.from || undefined} aria-invalid={!!rangeError}
                   onChange={(e) => set({ to: e.target.value })} />
            {rangeError && <span className="field__error">{rangeError}</span>}
          </div>
          <div className="field">
            <label className="field__label" htmlFor={`${uid}-size`}>Per page</label>
            <select id={`${uid}-size`} className="input" value={filters.size || String(f?.default_page_size ?? "")} onChange={(e) => set({ size: e.target.value })}>
              {f?.page_sizes.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {active.length > 0 && (
        <div className="filters__active">
          <span className="subtle">Filtered by</span>
          {active.map((k) => (
            <button key={k} type="button" className="filter-chip" onClick={() => set({ [k]: "" } as Partial<JobFilters>)} aria-label={`Remove filter ${k}`}>
              <Badge tone="info">
                {chipName(k, labels.field)}: {chipValue(k, filters[k], labels)} ✕
              </Badge>
            </button>
          ))}
          <Button size="sm" variant="ghost" onClick={clear}>
            Clear all
          </Button>
        </div>
      )}
    </Card>
  );
}
