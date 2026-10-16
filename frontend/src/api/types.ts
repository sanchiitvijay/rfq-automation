export type JobStatus = "queued" | "running" | "needs_review" | "ready" | "sending" | "sent" | "failed";
export type FlagType = "missing" | "suspicious" | "not_found";

export interface JobSummary {
  id: string;
  source: "extension" | "paste" | "upload" | "mailbot";
  subject: string;
  sender: string;
  status: JobStatus;
  phase: string;
  progress: number;
  eta_seconds: number | null;
  error: string | null;
  version: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  requested: number;
  found: number;
  not_found: number;
  fill_rate: number | null;
  suspicious: number;
  missing: number;
}

export interface SourcedCell {
  value: string;
  source_type: string;
  confidence: string;
  source: string;
  url?: string;
}

export interface SheetRow {
  product_id: string;
  kind: "ferguson" | "competitor";
  lookup_status: "Found" | "Not found" | "Manual";
  lookup_source: string;
  raw_token: string;
  context: string;
  qty: string | null;
  tried: string[];
  not_found_reason: string;
  cells: Record<string, SourcedCell>;
  supplier: Record<string, SourcedCell>;
}

export interface Flag {
  cell: string;
  product_id: string;
  column: string;
  type: FlagType;
  check: "code" | "llm";
  reason: string;
}

export interface QualityReport {
  flags: Flag[];
  fill_overall: number;
  fill_found: number;
  fill_by_column: Record<string, number>;
  fill_by_product: Record<string, number>;
  llm_status: string;
}

export interface JobItem {
  position: number;
  raw_token: string;
  product_id: string;
  kind: "ferguson" | "competitor";
  qty: string | null;
  context: string;
  origin: string;
  occurrences: number;
  lookup_status: string;
  lookup_source: string;
  notes: string;
}

export interface JobSend {
  id: number;
  version: number;
  to: string;
  cc: string;
  status: "queued" | "sending" | "sent" | "failed";
  error: string | null;
  attempts: number;
  created_at: string;
  sent_at: string | null;
  user?: string;
}

export interface JobDetail extends JobSummary {
  email: { subject: string; sender: string; date: string; body: string; attachments: string[]; has_raw: boolean };
  items: JobItem[];
  warnings: string[];
  notes: { product_id: string; note: string }[];
  report: QualityReport | null;
  events: { ts: string; phase: string; message: string }[];
  edits: { ts: string; version: number; product_id: string; column: string; old: string; new: string; note: string; user: string }[];
  sends: JobSend[];
}

export interface Incomplete {
  not_found: string[];
  missing: Record<string, string[]>;
  suspicious: number;
  complete: boolean;
}

export interface SheetData {
  version: number;
  status: JobStatus;
  columns: string[];
  rows: SheetRow[];
  flags: Flag[];
  report: QualityReport | null;
  incomplete: Incomplete;
  /** dropdown values per editable column: choices = the only allowed values, suggestions = values in use */
  options: Record<string, { choices?: string[]; suggestions?: string[] }>;
}

export interface CellEdit {
  product_id: string;
  column: string;
  value: string;
  note: string;
}

export interface Health {
  api: string;
  db: string;
  redis: string;
  queue: string;
  chrome: string;
  mode: string;
  sending: string;
  serpapi: string;
  ferguson_rate_per_minute: number;
}

export interface JobEvent {
  type: "snapshot" | "progress" | "status" | "done" | "created" | "sheet";
  job_id: string;
  job?: JobSummary;
  phase?: string;
  message?: string;
  progress?: number;
  eta_seconds?: number;
  version?: number;
}

export interface ImportChange {
  product_id: string;
  column: string;
  current: string;
  uploaded: string;
  base: string | null;
  status: "ok" | "invalid" | "conflict";
  message: string;
  cell: string;
}

export interface ImportPreview {
  ok: boolean;
  filename: string;
  file_job_id: string;
  file_version: number | null;
  current_version: number;
  changes: ImportChange[];
  errors: string[];
  warnings: string[];
  counts: { ok: number; invalid: number; conflict: number };
}

export interface JobPage {
  items: JobSummary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface FacetOption {
  value: string;
  label: string;
  count?: number;
}

export interface Facets {
  statuses: FacetOption[];
  sources: FacetOption[];
  sorts: FacetOption[];
  page_sizes: number[];
  default_page_size: number;
  received: { first: string | null; last: string | null };
  max_text: number;
  fields: FacetOption[];
  date_presets: { value: string; label: string; days: number }[];
}

export interface Suggestion {
  field: "product" | "subject" | "sender";
  label: string;
  value: string;
  count: number;
}

/** Filters as they appear in the URL (all strings, empty = not set). */
export interface JobFilters {
  q: string;
  subject: string;
  sender: string;
  product: string;
  status: string;
  source: string;
  from: string; // YYYY-MM-DD, local day
  to: string;
  sort: string;
  page: string;
  size: string;
}

export interface ExportFormats {
  download: { value: string; label: string; description: string; extension: string }[];
  downloads: { value: string; label: string }[];
  upload: { extensions: string[]; accept: string; label: string };
}
