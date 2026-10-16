interface Props {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}

/** Windowed page numbers: 1 … 4 5 [6] 7 8 … 20 */
function windowed(page: number, pages: number): (number | "gap")[] {
  const out: (number | "gap")[] = [];
  const around = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  let last = 0;
  for (const p of [...around].sort((a, b) => a - b)) {
    if (p - last > 1) out.push("gap");
    out.push(p);
    last = p;
  }
  return out;
}

export function Pagination({ page, pages, total, pageSize, onPage }: Props) {
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <nav className="pagination" aria-label="Pages">
      <span className="subtle num">
        {total === 0 ? "No results" : `Showing ${first}–${last} of ${total}`}
      </span>
      {pages > 1 && (
        <div className="pagination__pages">
          <button type="button" className="chip" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
            ‹ Prev
          </button>
          {windowed(page, pages).map((p, i) =>
            p === "gap" ? (
              <span key={`gap-${i}`} className="subtle">
                …
              </span>
            ) : (
              <button key={p} type="button" className="chip num" aria-current={p === page ? "page" : undefined} aria-pressed={p === page} onClick={() => onPage(p)}>
                {p}
              </button>
            ),
          )}
          <button type="button" className="chip" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
            Next ›
          </button>
        </div>
      )}
    </nav>
  );
}
