import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiUrl } from "./client";
import { keys } from "./hooks";
import type { JobDetail, JobEvent, JobSummary } from "./types";

const POLL_MS = 3000;

function mergeSummary(list: JobSummary[] | undefined, job: JobSummary): JobSummary[] {
  if (!list) return [job];
  const i = list.findIndex((j) => j.id === job.id);
  if (i === -1) return [job, ...list];
  const next = list.slice();
  next[i] = { ...next[i], ...job };
  return next;
}

/**
 * Live updates over Server-Sent Events. If the stream fails (proxy, Redis down…), it falls back to
 * polling every 3 s so the screen never goes stale. Returns "live" | "polling".
 */
export function useLiveUpdates(jobId?: string): "live" | "polling" {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"live" | "polling">("live");

  useEffect(() => {
    let poll: number | undefined;
    const path = jobId ? `/api/jobs/${jobId}/events` : "/api/events";
    const source = new EventSource(apiUrl(path));

    const refresh = () => {
      if (jobId) {
        void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      } else {
        void qc.invalidateQueries({ queryKey: keys.jobs });
      }
    };

    source.onmessage = (msg) => {
      setMode("live");
      let event: JobEvent;
      try {
        event = JSON.parse(msg.data) as JobEvent;
      } catch {
        return;
      }
      if (event.type === "progress") {
        const patch = {
          phase: event.message ?? event.phase ?? "",
          progress: event.progress ?? 0,
          eta_seconds: event.eta_seconds ?? null,
          status: "running" as const,
        };
        qc.setQueryData<JobSummary[]>(keys.jobs, (list) =>
          list?.map((j) => (j.id === event.job_id ? { ...j, ...patch } : j)),
        );
        qc.setQueryData<JobDetail>(keys.job(event.job_id), (d) => (d ? { ...d, ...patch } : d));
        return;
      }
      if (event.job) {
        const job = event.job;
        qc.setQueryData<JobSummary[]>(keys.jobs, (list) => mergeSummary(list, job));
        qc.setQueryData<JobDetail>(keys.job(event.job_id), (d) => (d ? { ...d, ...job } : d));
      }
      if (event.type === "done" || event.type === "status" || event.type === "sheet") {
        void qc.invalidateQueries({ queryKey: keys.job(event.job_id) });
        if (event.type === "sheet") void qc.invalidateQueries({ queryKey: keys.sheet(event.job_id) });
      }
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED && poll === undefined) {
        setMode("polling");
        poll = window.setInterval(refresh, POLL_MS);
      }
    };
    // Browsers reconnect EventSource on their own; poll meanwhile so nothing is missed.
    const watchdog = window.setInterval(() => {
      if (source.readyState !== EventSource.OPEN && poll === undefined) {
        setMode("polling");
        poll = window.setInterval(refresh, POLL_MS);
      } else if (source.readyState === EventSource.OPEN && poll !== undefined) {
        window.clearInterval(poll);
        poll = undefined;
        setMode("live");
      }
    }, 5000);

    return () => {
      source.close();
      window.clearInterval(watchdog);
      if (poll !== undefined) window.clearInterval(poll);
    };
  }, [jobId, qc]);

  return mode;
}
