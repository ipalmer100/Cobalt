import { useEffect, useMemo, useState } from "react";
import { commitEdits } from "../api";
import RevisionPrompt from "./RevisionPrompt";
import AutoTextarea from "./AutoTextarea";
import { categoryLabel, isMassEditable } from "../specCategory";
import type { BatchEditItem, SpecDetail as SpecDetailType, SpecSection } from "../types";

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
 * move together, and only through a save's own revision step. Editing
 * either directly is what would let a spec's stated revision drift from
 * its own audit trail.
 */
function isLocked(section: string, label: string): boolean {
  if (section === REVISION_HISTORY) return true;
  return section === "Product Description" && label.replace(/:$/, "").trim() === REVISION_NUMBER;
}

/** Identifies one editable cell, for keying buffered changes. */
function cellId(section: string, tableIndex: number | null | undefined, kind: string, a: string | number, b?: number) {
  return `${section}|${tableIndex ?? -1}|${kind}|${a}${b === undefined ? "" : `|${b}`}`;
}

/**
 * One spec at a time, edited as a unit.
 *
 * Cells are read-only until Edit is pressed, then changes are held in the
 * browser and nothing touches the document. Save asks what the revision
 * was and writes the changes and that statement together, so a spec can
 * never end up holding edited values with no Revision History row
 * accounting for them -- and an interrupted save leaves the document
 * exactly as it was.
 */
export default function SpecDetail({ spec, onChanged, defaultWho, who }: Props) {
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Map<string, { edit: BatchEditItem; original: string }>>(new Map());
  const [prompting, setPrompting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);

  // Switching specs mid-edit would silently strand the drafts against the
  // wrong document, so leaving edit mode is tied to the spec on screen.
  useEffect(() => {
    setEditing(false);
    setDrafts(new Map());
    setPrompting(false);
    setError(null);
  }, [spec.file_path]);

  // A dirty editor plus a browser close is the one way buffered changes can
  // be lost without the user deciding to lose them. Warn, as any editor does.
  useEffect(() => {
    if (drafts.size === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [drafts.size]);

  const pending = useMemo(() => {
    // A cell typed back to its starting value is not a change.
    return [...drafts.values()].filter((d) => d.edit.value !== d.original);
  }, [drafts]);

  function stage(id: string, edit: BatchEditItem, original: string) {
    setDrafts((prev) => {
      const next = new Map(prev);
      if (edit.value === original) next.delete(id);
      else next.set(id, { edit, original });
      return next;
    });
  }

  function draftValue(id: string, fallback: string): string {
    return drafts.get(id)?.edit.value ?? fallback;
  }

  function cancelEditing() {
    setEditing(false);
    setDrafts(new Map());
    setError(null);
  }

  async function commit(whoName: string, revisionText: string) {
    setBusy(true);
    setPromptError(null);
    try {
      await commitEdits(pending.map((d) => d.edit), whoName, revisionText);
      setDrafts(new Map());
      setEditing(false);
      setPrompting(false);
      onChanged();
    } catch (e) {
      // Kept in edit mode with the drafts intact: the changes are still
      // only in the browser, so there is nothing to reconcile -- the user
      // can fix the problem and save again.
      setPromptError(e instanceof Error ? e.message : String(e));
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
        {!isMassEditable(spec.category) && (
          <span className={`category-tag category-${spec.category}`}>{categoryLabel(spec.category)}</span>
        )}

        <div className="spec-edit-controls">
          {!editing && (
            <button className="primary" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {editing && (
            <>
              <span className="spec-dirty-count">
                {pending.length === 0
                  ? "No changes yet"
                  : `${pending.length} unsaved ${pending.length === 1 ? "change" : "changes"}`}
              </span>
              <button onClick={cancelEditing}>Cancel</button>
              <button
                className="primary"
                disabled={pending.length === 0}
                title={pending.length === 0 ? "Change something first" : undefined}
                onClick={() => {
                  setPromptError(null);
                  setPrompting(true);
                }}
              >
                Save…
              </button>
            </>
          )}
        </div>
      </div>

      <p className="spec-hint">
        {editing
          ? "Changes are held here until you save. Saving asks you to describe the revision."
          : "Read-only. Press Edit to make changes."}
      </p>

      {/* Not a warning: a blown film spec is a different kind of document,
          not a broken one. It says which sections make it one and what
          that changes, so the answer to "why isn't this in the grid?" is
          on the spec itself rather than somewhere else. */}
      {!isMassEditable(spec.category) && (
        <div className={`category-banner category-${spec.category}`}>
          <div className="category-banner-title">{categoryLabel(spec.category)} spec</div>
          <div className="category-banner-body">
            Edited here, one spec at a time — {categoryLabel(spec.category)} specs are not covered by Mass
            Edit. Everything below is fully editable.
            {spec.category_sections.length > 0 && (
              <> Categorised by {spec.category_sections.join(" and ")}.</>
            )}
          </div>
        </div>
      )}

      {error && <div className="error banner">{error}</div>}

      {spec.warnings.length > 0 && (
        <div className="warnings">
          {spec.warnings.map((w) => (
            <div key={w}>⚠ {w}</div>
          ))}
        </div>
      )}

      {Object.entries(spec.sections).map(([name, tables]) =>
        tables.map((section: SpecSection, ti) => {
          const locked = name === REVISION_HISTORY;
          return (
            <section key={`${name}:${section.table_index}:${ti}`} className="spec-section">
              <h3>
                {name}
                {section.variant && <span className="section-variant">{section.variant}</span>}
                {locked && <span className="section-locked">read-only · set by the revision you describe on save</span>}
              </h3>
              {section.rows.length === 0 && <p className="empty">No data.</p>}

              {section.shape === "records" && section.header_row && (
                <table className={`records-table detail-table${editing && !locked ? " editable" : ""}`}>
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
                        {row.map((cell, c) => {
                          const id = cellId(name, section.table_index, "record", r + 1, c);
                          const value = draftValue(id, cell);
                          const changed = drafts.has(id);
                          if (!editing || locked) {
                            return (
                              <td key={c} className="detail-readonly-cell">
                                {cell || "—"}
                              </td>
                            );
                          }
                          return (
                            <td key={c} className={changed ? "cell-dirty" : ""}>
                              <AutoTextarea
                                className="cell-editor"
                                value={value}
                                onChange={(e) =>
                                  stage(
                                    id,
                                    {
                                      path: spec.file_path,
                                      section: name,
                                      kind: "record",
                                      row: r + 1,
                                      col: c,
                                      value: e.target.value,
                                      table_index: section.table_index,
                                    },
                                    cell,
                                  )
                                }
                              />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {section.shape === "fields" && section.fields && (
                <dl className="fields-grid">
                  {Object.entries(section.fields).map(([label, value]) => {
                    const fieldLocked = locked || isLocked(name, label);
                    const id = cellId(name, section.table_index, "field", label);
                    const shown = draftValue(id, value);
                    const changed = drafts.has(id);
                    return (
                      <div className="field-pair" key={label}>
                        <dt>{label}</dt>
                        <dd>
                          {!editing || fieldLocked ? (
                            <span className={fieldLocked && editing ? "detail-locked" : ""}>{value || "—"}</span>
                          ) : (
                            <AutoTextarea
                              className={`detail-editor${changed ? " dirty" : ""}`}
                              value={shown}
                              onChange={(e) =>
                                stage(
                                  id,
                                  {
                                    path: spec.file_path,
                                    section: name,
                                    kind: "field",
                                    label,
                                    value: e.target.value,
                                    table_index: section.table_index,
                                  },
                                  value,
                                )
                              }
                            />
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              )}
            </section>
          );
        }),
      )}

      {prompting && (
        <RevisionPrompt
          editCount={pending.length}
          specSummary={`${spec.spec_number || "this spec"}`}
          defaultWho={who || defaultWho}
          busy={busy}
          error={promptError}
          onCancel={() => setPrompting(false)}
          onConfirm={commit}
        />
      )}
    </div>
  );
}
