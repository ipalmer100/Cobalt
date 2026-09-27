import { useState } from "react";
import { createBlankSpec, duplicateSpec } from "../api";
import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  onCreated: (path: string) => void;
  onClose: () => void;
  defaultWho: string;
}

function dirOf(path: string): string {
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx >= 0 ? path.slice(0, idx) : path;
}

export default function NewSpecModal({ root, entries, onCreated, onClose, defaultWho }: Props) {
  const supported = entries.filter((e) => e.supported);
  const [mode, setMode] = useState<"duplicate" | "blank">(supported.length > 0 ? "duplicate" : "blank");
  const [sourcePath, setSourcePath] = useState(supported[0]?.path ?? "");
  // A flat dropdown is fine for a dozen specs and useless for eighteen
  // hundred, which is what a real library holds -- duplicating a spec means
  // finding one specific document, so the picker has to be searchable.
  const [sourceQuery, setSourceQuery] = useState("");
  const [specNumber, setSpecNumber] = useState("");
  const [customer, setCustomer] = useState("");
  const [who, setWho] = useState(defaultWho);
  const [destFolder, setDestFolder] = useState(root);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const term = sourceQuery.trim().toLowerCase();
  const matches = term
    ? supported.filter((e) =>
        [e.spec_number, e.customer, e.path.split(/[\\/]/).pop()].some((f) =>
          (f ?? "").toLowerCase().includes(term),
        ),
      )
    : supported;

  async function submit() {
    if (!specNumber.trim() || !customer.trim() || !who.trim()) {
      setError("Spec #, Customer, and your name are all required.");
      return;
    }
    const destPath = `${destFolder.replace(/[/\\]+$/, "")}/${specNumber.trim()}.docx`;
    setBusy(true);
    setError(null);
    try {
      if (mode === "duplicate") {
        if (!sourcePath || !matches.some((e) => e.path === sourcePath)) {
          setError("Choose a spec to duplicate from the list.");
          setBusy(false);
          return;
        }
        await duplicateSpec(sourcePath, destPath, specNumber.trim(), customer.trim(), who.trim());
      } else {
        await createBlankSpec(destPath, specNumber.trim(), customer.trim(), who.trim());
      }
      onCreated(destPath);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>New Spec</h2>

        <div className="mode-toggle">
          <button className={mode === "duplicate" ? "active" : ""} onClick={() => setMode("duplicate")} disabled={supported.length === 0}>
            Duplicate existing
          </button>
          <button className={mode === "blank" ? "active" : ""} onClick={() => setMode("blank")}>
            Blank template
          </button>
        </div>

        {mode === "duplicate" && (
          <label className="modal-field">
            Duplicate from
            <input
              className="source-search"
              value={sourceQuery}
              onChange={(e) => setSourceQuery(e.target.value)}
              placeholder="Search spec # or customer…"
            />
            <select
              className="source-list"
              size={Math.min(8, Math.max(2, matches.length))}
              value={sourcePath}
              onChange={(e) => {
                setSourcePath(e.target.value);
                // Sensible default: a new spec usually belongs beside the
                // one it was copied from.
                setDestFolder(dirOf(e.target.value));
              }}
            >
              {matches.map((e) => (
                <option key={e.path} value={e.path}>
                  {e.spec_number} — {e.customer}
                </option>
              ))}
            </select>
            <span className="modal-hint">
              {term
                ? `${matches.length} of ${supported.length} specs match`
                : `${supported.length} spec${supported.length === 1 ? "" : "s"} to choose from`}
              . Data tables carry over as a starting point; Spec #, Customer, and Revision History reset.
            </span>
          </label>
        )}

        <label className="modal-field">
          New Spec #
          <input value={specNumber} onChange={(e) => setSpecNumber(e.target.value)} placeholder="e.g. EG1600" />
        </label>

        <label className="modal-field">
          Customer
          <input value={customer} onChange={(e) => setCustomer(e.target.value)} />
        </label>

        <label className="modal-field">
          Your name
          <input value={who} onChange={(e) => setWho(e.target.value)} />
        </label>

        <label className="modal-field">
          Destination folder
          <input value={destFolder} onChange={(e) => setDestFolder(e.target.value)} />
          <span className="modal-hint">File will be created as {destFolder.replace(/[/\\]+$/, "")}/{specNumber || "<Spec #>"}.docx</span>
        </label>

        {error && <div className="error">{error}</div>}

        <div className="modal-actions">
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" onClick={submit} disabled={busy}>
            {busy ? "Creating…" : "Create Spec"}
          </button>
        </div>
      </div>
    </div>
  );
}
