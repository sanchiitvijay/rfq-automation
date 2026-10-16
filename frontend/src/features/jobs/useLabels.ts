import { useMemo } from "react";
import { useFacets } from "../../api/hooks";

/** Status / source / field labels come from the server (GET /api/jobs/facets), not from the UI code. */
export function useLabels() {
  const facets = useFacets();
  return useMemo(() => {
    const map = (opts?: { value: string; label: string }[]) => new Map((opts ?? []).map((o) => [o.value, o.label]));
    const status = map(facets.data?.statuses);
    const source = map(facets.data?.sources);
    const field = map(facets.data?.fields);
    return {
      status: (v: string) => status.get(v) ?? v.replace(/_/g, " "),
      source: (v: string) => source.get(v) ?? v,
      field: (v: string) => field.get(v) ?? v,
    };
  }, [facets.data]);
}
