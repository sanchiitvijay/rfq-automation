import type { JobDetail } from "../../api/types";
import { Badge } from "../../components/ui";
import { pct } from "../../lib/format";
import { LOOKUP_SOURCE_LABEL } from "./sources";
import { SupplierTable } from "./SupplierTable";

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "danger" | "warning" }) {
  return (
    <div className={`stat ${tone ? `stat--${tone}` : ""}`}>
      <span className="stat__value num">{value}</span>
      <span className="stat__label">{label}</span>
    </div>
  );
}

export function SummaryPanel({ job }: { job: JobDetail }) {
  const report = job.report;
  const notFound = job.items.filter((i) => i.lookup_status === "Not found");
  const byColumn = Object.entries(report?.fill_by_column ?? {});
  return (
    <div className="summary">
      <div className="stats">
        <Stat label="Products requested" value={job.requested} />
        <Stat label="Found" value={job.found} />
        <Stat label="Not found" value={job.not_found} tone={job.not_found ? "danger" : undefined} />
        <Stat label="Fill rate" value={pct(report?.fill_overall)} />
        <Stat label="Flagged values" value={job.suspicious} tone={job.suspicious ? "warning" : undefined} />
        <Stat label="Missing fields" value={job.missing} />
      </div>
      {report && <p className="subtle">AI contradiction check: {report.llm_status}</p>}

      {job.warnings.length > 0 && (
        <div className="alert alert--warning">
          {job.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      )}

      <section>
        <h4 className="section-title">Not found <span className="subtle">(left blank, nothing guessed)</span></h4>
        {notFound.length === 0 ? (
          <p className="muted">Every requested product was found.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Line in the email</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {notFound.map((i) => (
                <tr key={i.product_id}>
                  <td className="mono">{i.product_id}</td>
                  <td className="subtle">{i.context}</td>
                  <td>{i.notes.replace(/^Not found: /, "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h4 className="section-title">Requested products</h4>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Product</th>
              <th>Type</th>
              <th>Qty</th>
              <th>Status</th>
              <th>Source</th>
              <th>Fill</th>
            </tr>
          </thead>
          <tbody>
            {job.items.map((i) => (
              <tr key={i.product_id}>
                <td className="num subtle">{i.position}</td>
                <td className="mono">
                  {i.product_id}
                  {i.occurrences > 1 && <span className="subtle"> ×{i.occurrences}</span>}
                </td>
                <td>{i.kind === "competitor" ? "Competitor / unknown" : "Ferguson"}</td>
                <td className="num">{i.qty ?? ""}</td>
                <td>
                  <Badge tone={i.lookup_status === "Not found" ? "danger" : "success"}>{i.lookup_status}</Badge>
                </td>
                <td className="subtle">{LOOKUP_SOURCE_LABEL[i.lookup_source] ?? i.lookup_source}</td>
                <td className="num">{pct(report?.fill_by_product[i.product_id])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {job.version > 0 && <SupplierTable jobId={job.id} />}

      {byColumn.length > 0 && (
        <section>
          <h4 className="section-title">Fill rate per column</h4>
          <div className="fill-cols">
            {byColumn.map(([col, rate]) => (
              <div key={col} className="fill-col">
                <span className="fill-col__name">{col}</span>
                <span className="fill-col__track">
                  <span className="fill-col__bar" style={{ width: `${rate}%` }} />
                </span>
                <span className="num subtle">{pct(rate)}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
