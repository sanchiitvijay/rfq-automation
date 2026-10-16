import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { JobFilters } from "../../api/types";

const FIELDS: (keyof JobFilters)[] = ["q", "subject", "sender", "product", "status", "source", "from", "to", "sort", "page", "size"];

/** Filters live in the URL: shareable, survive a reload, and the back button works. */
export function useJobFilters() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => {
    const f = {} as JobFilters;
    for (const k of FIELDS) f[k] = params.get(k) ?? "";
    return f;
  }, [params]);

  const set = useCallback(
    (patch: Partial<JobFilters>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          if (!("page" in patch)) next.delete("page"); // any filter change starts at page 1
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const clear = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);
  const active = FIELDS.filter((k) => !["page", "size", "sort"].includes(k) && filters[k]);
  return { filters, set, clear, active };
}
