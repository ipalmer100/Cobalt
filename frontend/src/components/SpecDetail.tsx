import { useState } from "react";
import { appendRevision } from "../api";
import type { SpecDetail as SpecDetailType } from "../types";

interface Props {
  spec: SpecDetailType;
  onChanged: () => void;
}

export default function SpecDetail({ spec, onChanged }: Props) {
  const [who, setWho] = useState("");
  const [revisionText, setRevisionText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitRevision() {
    if (!who.trim() || !revisionText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await appendRevision(spec.file_path, who.trim(), revisionText.trim());
      setRevisionText("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="spec-detail">
      <div className="spec-header">
        <h2>
          {spec.spec_number} — {spec.customer}
        </h2>
        <span className="spec-rev">Revision {spec.revision_number}</span>
      </div>

      {spec.warnings.length > 0 && (
        <div className="warnings">
          {spec.warnings.map((w) => (
            <div key={w}>⚠ {w}</div>
          ))}
        </div>
      )}

      {Object.entries(spec.sections).map(([name, section]) => (
        <section key={name} className="spec-section">
          <h3>{name}</h3>
          {section.rows.length === 0 && <p className="empty">No data.</p>}
          {section.shape === "records" && section.header_row && (
            <table className="records-table">
              <thead>
                <tr>
                  {section.header_row.map((h, i) => (
                    <th key={i}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {section.rows.slice(1).map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {section.shape === "fields" && section.fields && (
            <dl className="fields-grid">
              {Object.entries(section.fields).map(([label, value]) => (
                <div className="field-pair" key={label}>
                  <dt>{label}</dt>
                  <dd>{value || "—"}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      ))}

      <section className="spec-section revision-form">
        <h3>Add Revision</h3>
        <input placeholder="Your name" value={who} onChange={(e) => setWho(e.target.value)} />
        <input
          placeholder="What changed?"
          value={revisionText}
          onChange={(e) => setRevisionText(e.target.value)}
        />
        <button disabled={busy} onClick={submitRevision}>
          {busy ? "Saving…" : "Bump revision + log"}
        </button>
        {error && <div className="error">{error}</div>}
      </section>
    </div>
  );
}
