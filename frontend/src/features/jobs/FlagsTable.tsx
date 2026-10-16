import { useMemo, useState } from "react";
import type { Flag, FlagType } from "../../api/types";
import { Badge, EmptyState } from "../../components/ui";

const TYPE_LABEL: Record<FlagType, string> = { missing: "Missing", suspicious: "Check", not_found: "Not found" };
const TYPE_TONE = { missing: "missing", suspicious: "suspicious", not_found: "danger" } as const;

export function FlagsTable({ flags }: { flags: Flag[] }) {
  const [type, setType] = useState<FlagType | "all">("suspicious");
  const shown = useMemo(() => (type === "all" ? flags : flags.filter((f) => f.type === type)), [flags, type]);
  const count = (t: FlagType) => flags.filter((f) => f.type === t).length;
  return (
    <div className="flags">
      <div className="jobs-filters" role="group" aria-label="Flag type">
        {(["suspicious", "not_found", "missing", "all"] as const).map((t) => (
          <button key={t} type="button" className="chip" aria-pressed={type === t} onClick={() => setType(t)}>
            {t === "all" ? `All ${flags.length}` : `${TYPE_LABEL[t]} ${count(t)}`}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <EmptyState title="No flags of this type" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Cell</th>
              <th>Product</th>
              <th>Column</th>
              <th>Type</th>
              <th>Check</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={`${f.cell}-${f.type}`}>
                <td className="mono">{f.cell}</td>
                <td className="mono">{f.product_id}</td>
                <td>{f.column}</td>
                <td>
                  <Badge tone={TYPE_TONE[f.type]}>{TYPE_LABEL[f.type]}</Badge>
                </td>
                <td className="subtle">{f.check === "llm" ? "AI" : "Rule"}</td>
                <td>{f.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
