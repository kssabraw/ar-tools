import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createExport,
  downloadExport,
  getSummary,
  listExports,
  type CsvExportFormat,
  type CsvExportListItem,
} from "../../shared/api";
import { useSession } from "../SessionWorkspace";

// Exports tab (PRD §12): four CSV formats generated live from Postgres, frozen
// to Storage, and listed for re-download. Available to both Owner and VA (Export
// is ✓ for both in §11.2). The frontend never touches Storage — the backend
// returns a short-lived signed URL it opens.
const FORMAT_LABELS: Record<CsvExportFormat, string> = {
  flat: "Flat keyword list",
  topic_grouped: "Topic-grouped (.zip)",
  architecture: "Site architecture",
  linking: "Internal linking (edge list)",
};

function openDownload(url: string) {
  // The signed URL already carries a Content-Disposition: attachment (set
  // server-side at signing time), so opening it triggers a download.
  window.open(url, "_blank", "noopener");
}

export function ExportsView() {
  const { sessionId } = useSession();
  const qc = useQueryClient();

  const summary = useQuery({ queryKey: ["summary", sessionId], queryFn: () => getSummary(sessionId) });
  const exportsQ = useQuery({ queryKey: ["exports", sessionId], queryFn: () => listExports(sessionId) });

  const architectureReady = Boolean(summary.data?.architecture);

  const gen = useMutation({
    mutationFn: (format: CsvExportFormat) => createExport(sessionId, format),
    onSuccess: (res) => {
      openDownload(res.download_url);
      qc.invalidateQueries({ queryKey: ["exports", sessionId] });
    },
    onError: (e: Error) => alert(e.message),
  });

  const redownload = useMutation({
    mutationFn: (exportId: string) => downloadExport(exportId),
    onSuccess: (res) => openDownload(res.download_url),
    onError: (e: Error) => alert(e.message),
  });

  // architecture + linking both consume the generated site-architecture; if it
  // hasn't been built yet, gate both buttons rather than 400ing the user.
  const formats: CsvExportFormat[] = ["flat", "topic_grouped", "architecture", "linking"];
  const needsArchitecture = (f: CsvExportFormat) => f === "architecture" || f === "linking";

  return (
    <div>
      <div className="card">
        <p style={{ margin: 0, fontWeight: 600 }}>Download CSV</p>
        <p className="muted" style={{ marginTop: 4 }}>
          Generated live from the current data (your edits and exclusions are reflected). Each
          download is also saved as a snapshot below.
        </p>
        <div className="export-actions">
          {formats.map((f) => {
            const disabled =
              gen.isPending || (needsArchitecture(f) && !architectureReady);
            return (
              <button
                key={f}
                className="btn btn-ghost"
                style={{ width: "auto" }}
                disabled={disabled}
                title={
                  needsArchitecture(f) && !architectureReady
                    ? "Generate the site architecture first"
                    : undefined
                }
                onClick={() => gen.mutate(f)}
              >
                {gen.isPending && gen.variables === f ? (
                  <>
                    <span className="spinner-sm" />
                    Generating…
                  </>
                ) : (
                  FORMAT_LABELS[f]
                )}
              </button>
            );
          })}
        </div>
      </div>

      <h2 className="section-title" style={{ marginTop: 24 }}>
        Past exports
      </h2>
      {exportsQ.isLoading && <p className="muted">Loading exports…</p>}
      {exportsQ.isError && <p className="form-error">Couldn’t load past exports.</p>}
      {exportsQ.data && exportsQ.data.length === 0 && (
        <p className="muted">No exports yet. Generate one above.</p>
      )}
      {exportsQ.data && exportsQ.data.length > 0 && (
        <div className="table-scroll">
          <table className="kw-table">
            <thead>
              <tr>
                <th>Format</th>
                <th>Generated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {exportsQ.data.map((e: CsvExportListItem) => (
                <tr key={e.id}>
                  <td>{FORMAT_LABELS[e.format] ?? e.format}</td>
                  <td className="cell-muted">{new Date(e.generated_at).toLocaleString()}</td>
                  <td className="num">
                    <button
                      className="link-btn"
                      disabled={redownload.isPending}
                      onClick={() => redownload.mutate(e.id)}
                    >
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
