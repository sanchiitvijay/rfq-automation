import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  CellEdit, ExportFormats, Facets, Health, ImportPreview, JobDetail, JobFilters, JobPage, JobSend, JobSummary, SheetData, Suggestion,
} from "./types";

export const keys = {
  jobs: ["jobs"] as const,
  job: (id: string) => ["job", id] as const,
  sheet: (id: string) => ["sheet", id] as const,
  health: ["health"] as const,
};

/** Local calendar day → the UTC instant where it starts / ends, so "received on 16 Oct" means your 16 Oct. */
function dayBoundary(day: string, end: boolean): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const d = new Date(`${day}T${end ? "23:59:59.999" : "00:00:00"}`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function jobsQueryString(f: Partial<JobFilters>): string {
  const p = new URLSearchParams();
  for (const k of ["q", "subject", "sender", "product", "status", "source", "sort"] as const) {
    const v = f[k]?.trim();
    if (v) p.set(k, v);
  }
  const from = f.from ? dayBoundary(f.from, false) : null;
  const to = f.to ? dayBoundary(f.to, true) : null;
  if (from) p.set("created_from", from);
  if (to) p.set("created_to", to);
  if (f.page) p.set("page", f.page);
  if (f.size) p.set("page_size", f.size);
  return p.toString();
}

export function useJobs(filters: Partial<JobFilters>) {
  const qs = jobsQueryString(filters);
  const badRange = !!(filters.from && filters.to && filters.from > filters.to); // shown inline; no request
  return useQuery({
    queryKey: [...keys.jobs, qs],
    queryFn: () => api<JobPage>(`/api/jobs?${qs}`),
    enabled: !badRange,
    placeholderData: keepPreviousData, // keep the old page on screen while the next one loads
  });
}

export function useFacets() {
  return useQuery({ queryKey: ["facets"], queryFn: () => api<Facets>("/api/jobs/facets"), staleTime: 30_000 });
}

export function useSuggestions(text: string) {
  const q = text.trim();
  return useQuery({
    queryKey: ["suggest", q],
    queryFn: ({ signal }) => api<Suggestion[]>(`/api/jobs/suggest?q=${encodeURIComponent(q)}`, { signal }),
    enabled: q.length >= 2,
    staleTime: 15_000,
  });
}

export function useJob(id: string) {
  return useQuery({ queryKey: keys.job(id), queryFn: () => api<JobDetail>(`/api/jobs/${id}`) });
}

export function useSheet(id: string, enabled: boolean) {
  return useQuery({ queryKey: keys.sheet(id), queryFn: () => api<SheetData>(`/api/jobs/${id}/sheet`), enabled });
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: () => api<Health>("/api/health"), refetchInterval: 30_000 });
}

interface Created {
  job_id: string;
  created: boolean;
}

export function useCreateFromText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { subject: string; sender: string; body_text: string }) =>
      api<Created>("/api/jobs", { method: "POST", body: JSON.stringify({ source: "paste", ...v }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useUploadEml() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Created>("/api/jobs/upload", { method: "POST", body: form });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function usePatchSheet(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { version: number; edits: CellEdit[]; remove_rows?: { product_id: string; reason: string }[] }) =>
      api<SheetData>(`/api/jobs/${id}/sheet`, { method: "PATCH", body: JSON.stringify(v) }),
    onSuccess: (data) => {
      keepNewest(qc, id, data);
      void qc.invalidateQueries({ queryKey: keys.job(id) });
    },
  });
}

/** Never let an older response replace newer data that is already on screen. */
function keepNewest(qc: ReturnType<typeof useQueryClient>, id: string, data: SheetData) {
  qc.setQueryData<SheetData>(keys.sheet(id), (current) => (current && current.version > data.version ? current : data));
}

export function useRecheck(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<SheetData>(`/api/jobs/${id}/recheck`, { method: "POST" }),
    onSuccess: (data) => {
      keepNewest(qc, id, data);
      void qc.invalidateQueries({ queryKey: keys.job(id) });
    },
  });
}

export function useMarkReviewed(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { done: boolean; version: number }) =>
      api<JobSummary>(`/api/jobs/${id}/review?done=${v.done}&version=${v.version}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(id) }),
    onError: () => {
      void qc.invalidateQueries({ queryKey: keys.job(id) });
      void qc.invalidateQueries({ queryKey: keys.sheet(id) });
    },
  });
}

export function useImportPreview(id: string) {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<ImportPreview>(`/api/jobs/${id}/sheet/import`, { method: "POST", body: form });
    },
  });
}

export function useMailTest() {
  return useMutation({ mutationFn: () => api<{ ok: boolean; detail: string }>("/api/mail/test", { method: "POST" }) });
}

export interface SendBody {
  to: string;
  cc: string[];
  subject: string;
  body: string;
  confirm_incomplete: boolean;
  resend: boolean;
  idempotency_key: string;
}

export function useSend(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: SendBody) => api<JobSend>(`/api/jobs/${id}/send`, { method: "POST", body: JSON.stringify(v) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(id) }),
  });
}

export function useRetry(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<JobSummary>(`/api/jobs/${id}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(id) }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/api/jobs/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

export function useExportFormats() {
  return useQuery({ queryKey: ["export-formats"], queryFn: () => api<ExportFormats>("/api/exports/formats"), staleTime: Infinity });
}
