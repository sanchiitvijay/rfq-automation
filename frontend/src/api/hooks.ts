import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { CellEdit, Health, JobDetail, JobSend, JobSummary, SheetData } from "./types";

export const keys = {
  jobs: ["jobs"] as const,
  job: (id: string) => ["job", id] as const,
  sheet: (id: string) => ["sheet", id] as const,
  health: ["health"] as const,
};

export function useJobs() {
  return useQuery({ queryKey: keys.jobs, queryFn: () => api<JobSummary[]>("/api/jobs?limit=100") });
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
      qc.setQueryData(keys.sheet(id), data);
      void qc.invalidateQueries({ queryKey: keys.job(id) });
    },
  });
}

export function useRecheck(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<SheetData>(`/api/jobs/${id}/recheck`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData(keys.sheet(id), data);
      void qc.invalidateQueries({ queryKey: keys.job(id) });
    },
  });
}

export function useMarkReviewed(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (done: boolean) => api<JobSummary>(`/api/jobs/${id}/review?done=${done}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(id) }),
  });
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
