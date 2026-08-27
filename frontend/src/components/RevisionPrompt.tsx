import { useEffect, useRef, useState } from "react";

interface Props {
  /** How many cells are about to be written. */
  editCount: number;
  /** Specs affected, so a mass edit says what it is about to touch. */
  specSummary: string;
  defaultWho: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (who: string, revisionText: string) => void;
}

/**
 * The gate between editing and writing.
 *
 * Revisions are manual but regulatorily required, so this is where the two
 * halves of one action meet: nothing has been written to any spec yet, and
 * confirming writes the edits and the revision statement together. Both
 * fields are required, because a spec holding changed values with nothing
 * in its Revision History to account for them is exactly what this flow
 * exists to prevent.
 */
export default function RevisionPrompt({
  editCount,
  specSummary,
  defaultWho,
  busy,
  error,
  onCancel,
  onConfirm,
}: Props) {
  const [who, setWho] = useState(defaultWho);
  const [text, setText] = useState("");
  const textRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    // Straight into the description: the name is usually already filled in
    // from last time, and the description is the part that needs thought.
    textRef.current?.focus();
  }, []);

  const ready = who.trim() !== "" && text.trim() !== "";

  function submit() {
    if (!ready || busy) return;
    onConfirm(who.trim(), text.trim());
  }

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div className="modal revision-prompt" onClick={(e) => e.stopPropagation()}>
        <h2>Describe this revision</h2>
        <p className="revision-prompt-summary">
          {editCount} {editCount === 1 ? "change" : "changes"} to {specSummary}. Nothing has been
          written yet — saving records the changes and this revision together.
        </p>

        <label className="revision-prompt-field">
          <span>Your name</span>
          <input
            value={who}
            onChange={(e) => setWho(e.target.value)}
            placeholder="Who is making this revision"
            disabled={busy}
          />
        </label>

        <label className="revision-prompt-field">
          <span>What changed, and why</span>
          <textarea
            ref={textRef}
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Updated sealant supplier to Berry per customer request CR-4417"
            disabled={busy}
            onKeyDown={(e) => {
              // Ctrl/Cmd+Enter saves; plain Enter is a newline, since this
              // is prose and often runs to more than one line.
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
        </label>

        <p className="revision-prompt-note">
          This is written into each spec's Revision History, and its Revision # is bumped.
        </p>

        {error && <div className="error">{error}</div>}

        <div className="modal-actions">
          <button onClick={onCancel} disabled={busy}>
            Keep editing
          </button>
          <button
            className="primary"
            onClick={submit}
            disabled={!ready || busy}
            title={ready ? undefined : "Both your name and a description are required"}
          >
            {busy ? "Saving…" : "Save revision"}
          </button>
        </div>
      </div>
    </div>
  );
}
