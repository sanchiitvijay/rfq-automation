import { useMemo, useState } from "react";
import { useSheet } from "../../api/hooks";
import type { SourcedCell } from "../../api/types";
import { Badge, EmptyState } from "../../components/ui";
import { SOURCE_TYPE_LABEL, SourceLink } from "./sources";

interface Line {
  product_id: string;
  field: string;
  supplier: boolean;
  cell: SourcedCell;
}

/** Every filled value with where it came from and a link to that page or PDF (same as the Sources sheet). */
export function SourcesPanel({ jobId }: { jobId: string }) {
  const sheet = useSheet(jobId, true);
  const [product, setProduct] = useState("all");
  const [query, setQuery] = useState("");
  const lines = useMemo<Line[]>(() => {
    const out: Line[] = [];
    for (const r of sheet.data?.rows ?? []) {
      for (const [field, cell] of Object.entries(r.cells)) out.push({ product_id: r.product_id, field, supplier: false, cell });
      for (const [field, cell] of Object.entries(r.supplier ?? {})) out.push({ product_id: r.product_id, field, supplier: true, cell });
    }
    return out;
  }, [sheet.data]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter(
      (l) =>
        (product === "all" || l.product_id === product) &&
        (!q || `${l.field} ${l.cell.value} ${l.cell.source} ${l.cell.source_type}`.toLowerCase().includes(q)),
    );
  }, [lines, product, query]);

  if (sheet.isLoading) return <p className="muted">Loading sources…</p>;
  if (sheet.isError) return <div className="alert alert--error">{sheet.error.message}</div>;
  if (!lines.length) return <EmptyState title="No values yet" />;
  const products = [...new Set(lines.map((l) => l.product_id))];

  return (
    <div className="sources">
      <div className="sources__filters">
        <label className="field">
          <span className="field__label">Product</span>
          <select className="input" value={product} onChange={(e) => setProduct(e.target.value)}>
            <option value="all">All products</option>
            {products.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="field sources__search">
          <span className="field__label">Search</span>
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="column, value or source…" />
        </label>
        <span className="subtle">{shown.length} values</span>
      </div>
      <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Product</th>
            <th>Field</th>
            <th>Value</th>
            <th>Source</th>
            <th>Confidence</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((l, i) => (
            <tr key={`${l.product_id}-${l.supplier}-${l.field}-${i}`}>
              <td className="mono">{l.product_id}</td>
              <td>
                {l.field}
                {l.supplier && <span className="subtle"> · supplier</span>}
              </td>
              <td className="sources__value" title={l.cell.value}>
                {l.cell.value}
              </td>
              <td>
                <Badge tone={l.cell.source_type === "manual_edit" ? "info" : "neutral"}>
                  {SOURCE_TYPE_LABEL[l.cell.source_type] ?? l.cell.source_type}
                </Badge>
                <div className="subtle">{l.cell.source}</div>
              </td>
              <td>{l.cell.confidence}</td>
              <td className="nowrap">
                <SourceLink cell={l.cell} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
