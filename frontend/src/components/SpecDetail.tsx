import { useEffect, useRef, useState } from "react";
import { appendRevision, writeCell, writeField } from "../api";
import type { SpecDetail as SpecDetailType, SpecSection } from "../types";

interface Props {
  spec: SpecDetailType;
  onChanged: () => void;
  defaultWho: string;
  who: string;
}

const REVISION_HISTORY = "Revision History";
const REVISION_NUMBER = "Revision #";

/**
 * Locked exactly as the mass-edit grid is, and for the same reason: the
 * Revision History table and Product Description's Revision # only ever
 * move together, through "Add Revision". Editing either directly is what
 * would let a spec's stated revision drift from its own audit trail.
 */
function isLocked(section: string, label: string): boolean {
  if (section === REVISION_HISTORY) return true;
  return section === "Product Description" && label.replace(/:$/, "").trim() === REVISION_NUMBER;
}

/** A cell that saves on blur, showing whether it saved or failed. */
function EditableValue({
  value,
  disabled,
  onCommit,
}: {
  value: string;
  disabled?: boolean;
  onCommit: (next: string) => Promise<void>;
}) {
  const [local, setLocal] = useState(value);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const editing = useRef(false);

  useEffect(() => {
    // Saving any one value reloads the whole spec, so every other cell gets
    // a fresh `value` prop. Resyncing the cell that currently has focus
    // would wipe what someone is part-way through typing.
    if (editing.current) return;
    setLocal(value);
  }, [value]);

  // A brief confirmation, then back to normal -- editing one spec at a time
  // means there's no row highlight to lean on, so the cell says so itself.
  useEffect(() => {
    if (state !== "saved") return;
    const timer = setTimeout(() => setState("idle"), 1200);
    return () => clearTimeout(timer);
  }, [state]);

  if (disabled) return <span className="detail-locked">{value || "—"}</span>;

  return (
    <textarea
      ref={ref}
      className={`detail-editor ${state}`}
      rows={Math.min(local.split("\n").length, 6)}
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      onFocus={() => {
        editing.current = true;
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          ref.current?.blur();
        } else if (e.key === "Escape") {
          e.preventDefault();
          editing.current = false;
          setLocal(value);
          setState("idle");
          ref.current?.blur();
        }
      }}
      onBlur={async () => {
        editing.current = false;
        if (local === value) return;
        setState("saving");
        try {
          await onCommit(local);
          setState("saved");
        } catch {
          setLocal(value); // put back what's actually in the document
          setState("error");
        }
      }}
    />
  );
}

export default function SpecDetail({ spec, onChanged, defaultWho, who }: Props) {
  const [revisionWho, setRevisionWho] = useState(defaultWho);
  const [revisionText, setRevisionText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRevisionWho(defaultWho);
  }, [defaultWho]);

  async function submitRevision() {
    if (!revisionWho.trim() || !revisionText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await appendRevision(spec.file_path, revisionWho.trim(), revisionText.trim());
      setRevisionText("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveCell(section: SpecSection, name: string, row: number, col: number, value: string) {
    setError(null);
    try {
      await writeCell(spec.file_path, name, row, col, value, who, section.table_index);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  }

  async function saveField(section: SpecSection, name: string, label: string, value: string) {
    setError(null);
    try {
      await writeField(spec.file_path, name, label, value, who, section.table_index);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  }

  return (
    <div className="spec-detail">
      <div className="spec-header">
        <h2>
          {spec.spec_number} — {spec.customer}
        </h2>
        <span className="spec-rev">Revision {spec.revision_number}</span>
        <span className="spec-hint">Click any value to edit it</span>
      </div>

      {error && <div className="error banner">{error}</div>}

      {spec.warnings.length > 0 && (
        <div className="warnings">
          {spec.warnings.map((w) => (
            <div key={w}>⚠ {w}</div>
          ))}
        </div>
      )}

      {Object.entries(spec.sections).map(([name, tables]) =>
        tables.map((section, ti) => {
          const locked = name === REVISION_HISTORY;
          return (
            <section key={`${name}:${section.table_index}:${ti}`} className="spec-section">
              <h3>
                {name}
                {section.variant && <span className="section-variant">{section.variant}</span>}
                {locked && <span className="section-locked">read-only · use Add Revision</span>}
              </h3>
              {section.rows.length === 0 && <p className="empty">No data.</p>}

              {section.shape === "records" && section.header_row && (
                <table className="records-table detail-table">
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
                          <td key={c}>
                            <EditableValue
                              value={cell}
                              disabled={locked}
                              onCommit={(next) => saveCell(section, name, r + 1, c, next)}
                            />
                          </td>
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
                      <dd>
                        <EditableValue
                          value={value}
                          disabled={locked || isLocked(name, label)}
                          onCommit={(next) => saveField(section, name, label, next)}
                        />
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
          );
        }),
      )}

      <section className="spec-section revision-form">
        <h3>Add Revision</h3>
        <input placeholder="Your name" value={revisionWho} onChange={(e) => setRevisionWho(e.target.value)} />
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
