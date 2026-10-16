import type { SourcedCell } from "../../api/types";

export const SOURCE_TYPE_LABEL: Record<string, string> = {
  ferguson_page: "Ferguson page",
  ferguson_rfq_sample: "Ferguson sample RFQ",
  spec_sheet: "Spec sheet",
  validated_rule: "Validated rule",
  sibling_products: "Sibling products",
  same_product_description: "Product description",
  serpapi: "Google (SerpApi)",
  manual_edit: "Edited by hand",
  earlier_run: "Earlier run",
};

export const LOOKUP_SOURCE_LABEL: Record<string, string> = {
  live: "ferguson.com page",
  cache: "ferguson.com page (cached)",
  "serpapi+catalog": "SerpApi + catalog",
  serpapi: "SerpApi only",
  catalog: "Backup catalog",
  manual: "Entered by hand",
  none: "",
};

/** Short, honest label for where a link points. */
export function linkLabel(url: string): string {
  try {
    const u = new URL(url);
    if (u.hostname === "api.ferguson.com") return "PDF";
    if (u.hostname.endsWith("ferguson.com")) return "Page";
    return u.hostname;
  } catch {
    return "link";
  }
}

export function isSafeUrl(url: string | undefined): url is string {
  return !!url && /^https?:\/\/[^\s"<>|]+$/.test(url);
}

/** Several picture URLs can be stored as "a|b": show the "_primary" one, else the first. */
export function primaryPicture(value: string): string | null {
  const urls = value.split("|").map((u) => u.trim()).filter(isSafeUrl);
  return urls.find((u) => u.includes("_primary")) ?? urls[0] ?? null;
}

export function SourceLink({ cell }: { cell: SourcedCell }) {
  if (!isSafeUrl(cell.url)) return <span className="subtle" title="Rule-based or typed in: there is no single page to link to">–</span>;
  return (
    <a href={cell.url} target="_blank" rel="noopener noreferrer" title={cell.url}>
      {linkLabel(cell.url)} ↗
    </a>
  );
}
