import { apiUrl } from "../../api/client";
import { useExportFormats } from "../../api/hooks";
import { Menu } from "../../components/ui";

interface Props {
  jobId: string;
  version: number;
}

/** "Download ▾": RFQ or Summary, in every format the server offers (.xlsx, .xls, .csv…). */
export function DownloadMenu({ jobId, version }: Props) {
  const formats = useExportFormats();
  const f = formats.data;
  return (
    <Menu
      label={`Download${version > 1 ? ` v${version}` : ""}`}
      width={320}
      placeholder={!f ? (formats.isError ? "Download formats unavailable." : "Loading…") : undefined}
      sections={(f?.downloads ?? []).map((what) => ({
        title: what.label,
        items: f!.download.map((fmt) => ({
          key: `${what.value}-${fmt.value}`,
          label: fmt.label,
          description: fmt.description,
          href: apiUrl(`/api/jobs/${jobId}/export`, { what: what.value, format: fmt.value }),
          download: true,
        })),
      }))}
    />
  );
}
