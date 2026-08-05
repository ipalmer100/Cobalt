import { useEffect, useState } from "react";
import { getAuditLog } from "../api";
import type { AuditLogEntry } from "../types";

interface Props {
  refreshToken: number;
}

function describe(e: AuditLogEntry): string {
  switch (e.action) {
    case "write_cell":
      return `${e.section}: changed to "${e.new_value}" (was "${e.old_value ?? "—"}")`;
    case "write_field":
      return `${e.section} → ${e.label}: changed to "${e.new_value}" (was "${e.old_value ?? "—"}")`;
    case "append_row":
      return `${e.section}: added row [${(e.values ?? []).join(", ")}]`;
    case "apply_revision":
      return `Revision bumped to ${e.revision_number}: "${e.revision_text}"`;
    case "convert_doc":
      return `Converted legacy .doc to .docx`;
    case "duplicate_spec":
      return `Created by duplicating an existing spec (customer: ${e.customer})`;
    case "create_blank_spec":
      return `Created from blank template (customer: ${e.customer})`;
    default:
      return e.action;
  }
}

function fileName(path?: string): string {
  if (!path) return "—";
  return path.split(/[\\/]/).pop() ?? path;
}

export default function AuditLogView({ refreshToken }: Props) {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getAuditLog()
      .then((res) => setEntries(res.entries))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [refreshToken]);

  return (
    <div className="audit-log-view">
      <div className="audit-log-note">
        This is the app's own change log — separate from each spec's Revision History table.
        Nothing here is ever written into a .docx file.
      </div>
      {loading && <div className="loading">Loading…</div>}
      {error && <div className="error">{error}</div>}
      <table className="records-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Who</th>
            <th>Spec</th>
            <th>File</th>
            <th>What happened</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i}>
              <td>{new Date(e.timestamp).toLocaleString()}</td>
              <td>{e.who || "—"}</td>
              <td>{e.spec_number ?? "—"}</td>
              <td title={e.file_path ?? e.dest_path}>{fileName(e.file_path ?? e.dest_path)}</td>
              <td>{describe(e)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && entries.length === 0 && <div className="empty">No changes logged yet.</div>}
    </div>
  );
}
