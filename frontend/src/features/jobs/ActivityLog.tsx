import type { JobDetail } from "../../api/types";
import { Badge } from "../../components/ui";
import { formatTime } from "../../lib/format";

export function ActivityLog({ job }: { job: JobDetail }) {
  return (
    <div className="activity">
      <section>
        <h4 className="section-title">Sent</h4>
        {job.sends.length === 0 ? (
          <p className="muted">Not sent yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>To</th>
                <th>Version</th>
                <th>Status</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {job.sends.map((s) => (
                <tr key={s.id}>
                  <td className="num subtle">{formatTime(s.sent_at ?? s.created_at)}</td>
                  <td>
                    {s.to}
                    {s.cc && <span className="subtle"> cc {s.cc}</span>}
                  </td>
                  <td className="num">v{s.version}</td>
                  <td>
                    <Badge tone={s.status === "sent" ? "success" : s.status === "failed" ? "danger" : "info"} title={s.error ?? undefined}>
                      {s.status}
                      {s.attempts > 1 ? ` (${s.attempts} tries)` : ""}
                    </Badge>
                    {s.error && <div className="subtle">{s.error}</div>}
                  </td>
                  <td className="subtle">{s.user}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section>
        <h4 className="section-title">Edits</h4>
        {job.edits.length === 0 ? (
          <p className="muted">No manual edits.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>By</th>
                <th>Product</th>
                <th>Column</th>
                <th>Change</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {[...job.edits].reverse().map((e, i) => (
                <tr key={i}>
                  <td className="num subtle">{formatTime(e.ts)}</td>
                  <td>{e.user}</td>
                  <td className="mono">{e.product_id}</td>
                  <td>{e.column}</td>
                  <td>
                    <span className="subtle">{e.old || "blank"}</span> → {e.new || <span className="subtle">blank</span>}
                  </td>
                  <td className="subtle">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section>
        <h4 className="section-title">Processing timeline</h4>
        <ol className="timeline">
          {job.events.map((e, i) => (
            <li key={i}>
              <span className="num subtle">{formatTime(e.ts)}</span> <strong>{e.phase}</strong> <span className="muted">{e.message !== e.phase ? e.message : ""}</span>
            </li>
          ))}
        </ol>
      </section>
      {job.notes.length > 0 && (
        <section>
          <h4 className="section-title">Notes</h4>
          <ul className="notes">
            {job.notes.map((n, i) => (
              <li key={i}>
                <span className="mono">{n.product_id}</span> {n.note}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
