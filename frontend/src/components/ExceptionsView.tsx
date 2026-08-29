import { useEffect, useState } from "react";
import { assignException, getExceptions, unassignException } from "../api";
import type { ExceptionsResponse } from "../types";

interface Props {
  refreshToken: number;
  who: string;
  onResolved: () => void;
}

/**
 * The human-in-the-loop queue.
 *
 * The parser files a table under a canonical section only when it can
 * tell confidently -- the exact section name, a known alias, or a qualified
 * variant of one ("Process Routing - Duplex"). Everything else lands here
 * rather than being guessed at, because a Press Specification table quietly
 * filed under Process Routing would corrupt what people read off the grid.
 *
 * Decisions are keyed by heading text and saved into the vault, so
 * allocating "Quality Issues" once covers every spec in the archive that
 * uses that heading, for everyone who opens the folder.
 */
export default function ExceptionsView({ refreshToken, who, onResolved }: Props) {
  const [data, setData] = useState<ExceptionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getExceptions()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [refreshToken]);

  async function assign(heading: string, section: string) {
    if (!section) return;
    setBusy(heading);
    setError(null);
    try {
      await assignException(heading, section, who);
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function unassign(heading: string) {
    setBusy(heading);
    setError(null);
    try {
      await unassignException(heading, who);
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) return <div className="loading">Loading…</div>;
  if (!data) return <div className="error">{error ?? "No data."}</div>;

  const ignore = data.ignore_value;

  return (
    <div className="exceptions-view">
      {error && <div className="error banner">{error}</div>}

      <p className="exceptions-intro">
        Tables whose heading doesn&rsquo;t clearly match a known section. Nothing here is
        guessed at &mdash; allocate each one and its rows join that section&rsquo;s Mass Edit view.
        A decision applies to every spec using the same heading and is saved with the vault.
      </p>

      {data.pending.length === 0 && (
        <div className="empty">Nothing to allocate &mdash; every table matched a section.</div>
      )}

      {data.pending.map((group) => (
        <section key={group.key} className="exception-card">
          <div className="exception-head">
            <h3>{group.heading || "(no heading)"}</h3>
            <span className="exception-meta">
              {group.shape} &middot; {group.spec_count} spec{group.spec_count === 1 ? "" : "s"}
            </span>
          </div>

          <div className="exception-specs">
            {group.specs.map((s) => (
              <span key={`${s.path}:${s.table_index}`} className="exception-spec-chip" title={s.path}>
                {s.spec_number || s.path.split(/[\\/]/).pop()} ({s.row_count} rows)
              </span>
            ))}
          </div>

          {group.preview.length > 0 && (
            <div className="exception-preview">
              <table className="records-table">
                <tbody>
                  {group.preview.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        <td key={c}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="exception-actions">
            <select
              value={choice[group.key] ?? ""}
              onChange={(e) => setChoice((prev) => ({ ...prev, [group.key]: e.target.value }))}
            >
              <option value="">Allocate to…</option>
              {data.sections.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button
              disabled={!choice[group.key] || busy === group.heading}
              onClick={() => assign(group.heading, choice[group.key])}
            >
              {busy === group.heading ? "Saving…" : "Assign"}
            </button>
            <button
              className="secondary"
              disabled={busy === group.heading}
              onClick={() => assign(group.heading, ignore)}
              title="Not a spec section — stop listing it here"
            >
              Not a spec section
            </button>
          </div>
        </section>
      ))}

      {data.resolved.length > 0 && (
        <section className="exceptions-resolved">
          <h3>Already allocated</h3>
          <table className="records-table">
            <thead>
              <tr>
                <th>Heading</th>
                <th>Allocated to</th>
                <th>Who</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.resolved.map((m) => (
                <tr key={m.heading}>
                  <td>{m.heading}</td>
                  <td>{m.section === ignore ? <em>not a spec section</em> : m.section}</td>
                  <td>{m.who || "—"}</td>
                  <td>
                    <button
                      className="secondary"
                      disabled={busy === m.heading}
                      onClick={() => unassign(m.heading)}
                    >
                      Undo
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
