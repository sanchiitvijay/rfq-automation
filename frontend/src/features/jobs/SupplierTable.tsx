import { useSheet } from "../../api/hooks";
import { Badge } from "../../components/ui";
import { LOOKUP_SOURCE_LABEL, SOURCE_TYPE_LABEL, isSafeUrl } from "./sources";

/** Who sells each product, part numbers, price and stock: every value carries its source on hover. */
export function SupplierTable({ jobId }: { jobId: string }) {
  const sheet = useSheet(jobId, true);
  const rows = sheet.data?.rows ?? [];
  if (!rows.length) return null;
  return (
    <section>
      <h4 className="section-title">
        Supplier <span className="subtle">(price and stock come from the live page or Google when available, otherwise from the 2026-09-24 catalog; hover a value for its source)</span>
      </h4>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Product</th>
              <th>Supplier</th>
              <th>Brand</th>
              <th>Mfr part #</th>
              <th>Ferguson part #</th>
              <th>Price (USD)</th>
              <th>Availability</th>
              <th>Found via</th>
              <th>Links</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const s = r.supplier ?? {};
              const cell = (k: string) => {
                const c = s[k];
                if (!c) return <span className="subtle">–</span>;
                return <span title={`${SOURCE_TYPE_LABEL[c.source_type] ?? c.source_type}: ${c.source}`}>{c.value}</span>;
              };
              const page = s["Product page"]?.value;
              const spec = s["Spec sheet"]?.value;
              return (
                <tr key={r.product_id}>
                  <td className="mono">{r.product_id}</td>
                  <td>{r.lookup_status === "Not found" ? <Badge tone="danger">Not found</Badge> : cell("Supplier")}</td>
                  <td>{cell("Brand")}</td>
                  <td className="mono">{cell("Manufacturer Part #")}</td>
                  <td className="mono">{cell("Ferguson Part #")}</td>
                  <td className="num">{cell("Price (USD)")}</td>
                  <td>{cell("Availability")}</td>
                  <td className="subtle">{LOOKUP_SOURCE_LABEL[r.lookup_source] ?? r.lookup_source}</td>
                  <td className="nowrap">
                    {isSafeUrl(page) && (
                      <a href={page} target="_blank" rel="noopener noreferrer">
                        Page ↗
                      </a>
                    )}
                    {isSafeUrl(spec) && (
                      <>
                        {" "}
                        <a href={spec} target="_blank" rel="noopener noreferrer">
                          Spec PDF ↗
                        </a>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
