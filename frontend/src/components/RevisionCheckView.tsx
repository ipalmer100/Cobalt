import { useEffect, useState } from "react";
import { getRevisionCheck } from "../api";
import type { RevisionCheckResponse, RevisionFinding } from "../types";

interface Props {
  refreshToken: number;
  onOpenSpec: (path: string) => void;
}

const LABELS: Record<RevisionFinding["kind"], string> = {
  stated_missing: "States no revision",
  history_missing: "No revision history",
  mismatch: "Disagrees with its history",
  out_of_sequence: "Numbering out of sequence",
  trailing_blank: "Blank row at the end of the history",
};

const EXPLANATIONS: Record<RevisionFinding["kind"], string> = {
  stated_missing: "Product Description has no Revision # value, so the spec doesn't state its own revision.",
  history_missing: "There's no revision history to check the stated revision against.",
  mismatch: "The two places a spec states its revision don't agree, so it doesn't establish which version it is.",
  out_of_sequence:
    "A revision number repeats or goes backwards. Specs revised by an older build of Cobalt were restarted at 01 — those look like this.",
  trailing_blank:
    "Harmless on its own, but older builds read a blank final row as the previous revision and restarted the numbering at 01.",
};

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/**
 * Which specs can't say what revision they are.
 *
 * A spec states its revision twice -- the Revision # field, and the last row
 * of Revision History -- and those must agree. This lists the ones where
 * they don't, plus the conditions that cause it.
 *
 * Deliberately read-only. Renumbering a regulated document is the spec
 * owner's decision: this says what each source claims and what the next
 * revision would continue from, and leaves the fix to a person.
 */
export default function RevisionCheckView({ refreshToken, onOpenSpec }: Props) {
  const [data, setData] = useState<RevisionCheckResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getRevisionCheck()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [refreshToken]);

  if (loading && !data) return <div className="loading">Checking revisions…</div>;
  if (error) return <div className="error banner">{error}</div>;
  if (!data) return null;

  // Grouped by spec: one spec usually trips several of these at once, and
  // they're one job to fix, not three.
  const bySpec = new Map<string, RevisionFinding[]>();
  for (const finding of data.findings) {
    const list = bySpec.get(finding.path);
    if (list) list.push(finding);
    else bySpec.set(finding.path, [finding]);
  }

  return (
    <div className="revision-check-view">
      <p className="revision-check-note">
        A spec states its revision in two places — the <strong>Revision #</strong> field and the last
        row of <strong>Revision History</strong> — and they have to agree. Nothing here is changed
        automatically: renumbering a spec is your call.
      </p>

      <div className="revision-check-summary">
        <span className="revision-check-stat">
          <strong>{data.checked}</strong> specs checked
        </span>
        <span className="revision-check-stat clean">
          <strong>{data.clean}</strong> consistent
        </span>
        <span className={`revision-check-stat${bySpec.size > 0 ? " flagged" : ""}`}>
          <strong>{bySpec.size}</strong> needing a look
        </span>
      </div>

      {bySpec.size === 0 && data.unreadable.length === 0 && (
        <div className="revision-check-clean">
          Every spec's stated revision matches its revision history.
        </div>
      )}

      {[...bySpec.entries()].map(([path, findings]) => (
        <div className="revision-check-card" key={path}>
          <div className="revision-check-card-head">
            <button className="revision-check-open" onClick={() => onOpenSpec(path)}>
              {findings[0].spec_number || fileName(path)}
            </button>
            <span className="revision-check-file" title={path}>
              {fileName(path)}
            </span>
            {findings[0].stated && (
              <span className="revision-check-pair">
                states <code>{findings[0].stated}</code>
              </span>
            )}
            {findings[0].history_last && (
              <span className="revision-check-pair">
                history ends <code>{findings[0].history_last}</code>
              </span>
            )}
          </div>

          {findings.map((finding, i) => (
            <div className={`revision-check-finding ${finding.kind}`} key={i}>
              <div className="revision-check-kind">{LABELS[finding.kind]}</div>
              <div className="revision-check-detail">{finding.detail}</div>
              <div className="revision-check-why">{EXPLANATIONS[finding.kind]}</div>
              {finding.continues_from && (
                <div className="revision-check-next">
                  Left as is, the next revision here would continue from{" "}
                  <code>{finding.continues_from}</code>.
                </div>
              )}
            </div>
          ))}
        </div>
      ))}

      {data.unreadable.length > 0 && (
        <div className="revision-check-unreadable">
          <h3>Couldn't be read</h3>
          {data.unreadable.map((u) => (
            <div key={u.path}>
              <strong>{fileName(u.path)}</strong> — {u.error}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
