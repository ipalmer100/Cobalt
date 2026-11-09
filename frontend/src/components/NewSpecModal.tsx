import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { createBlankSpec, duplicateSpec } from "../api";
import { normalizeSpecNumber } from "../specNumber";
import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  onCreated: (path: string) => void;
  onClose: () => void;
  defaultWho: string;
}

const ROW_HEIGHT_ESTIMATE = 46;
const LIST_MAX_HEIGHT = 230;
const LIST_MIN_HEIGHT = 92;

function dirOf(path: string): string {
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx >= 0 ? path.slice(0, idx) : path;
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

// The folder a spec sits in, relative to the vault root. The whole reason
// the picker needs it: a library organised by customer holds the same spec
// number under two customers, and "EG1000 - ACME Corp" then names two
// different documents.
function relativeFolder(root: string, path: string): string {
  const normRoot = root.replace(/[\\/]+$/, "");
  const rest = path.startsWith(normRoot) ? path.slice(normRoot.length) : path;
  const parts = rest.split(/[\\/]/).filter(Boolean);
  parts.pop();
  return parts.join(" / ");
}

// Paths come back from the backend using the host's separator and get
// compared against one this screen built, so compare them in one form.
// Case-insensitively because the libraries this runs against are on
// Windows, where two names differing only in case are the same file.
function samePath(a: string, b: string): boolean {
  const norm = (p: string) => p.replace(/[\\/]+/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

export default function NewSpecModal({ root, entries, onCreated, onClose, defaultWho }: Props) {
  // Sorted by spec number, not by whatever order the filesystem walk
  // produced. An unsorted list of a few thousand specs cannot be scanned,
  // only searched, and the one thing a person always knows about the spec
  // they want to copy is roughly where its number falls.
  const supported = useMemo(
    () =>
      entries
        .filter((e) => e.supported)
        .sort(
          (a, b) =>
            (a.spec_number ?? "").localeCompare(b.spec_number ?? "") || a.path.localeCompare(b.path),
        ),
    [entries],
  );

  const [mode, setMode] = useState<"duplicate" | "blank">(supported.length > 0 ? "duplicate" : "blank");
  // Nothing is selected until someone selects it. This used to default to
  // whichever spec the filesystem walk happened to return first, which is
  // an arbitrary document to copy a new spec from -- an extra click is far
  // cheaper than silently duplicating the wrong spec.
  const [sourcePath, setSourcePath] = useState<string | null>(null);
  const [sourceQuery, setSourceQuery] = useState("");
  const [specNumber, setSpecNumber] = useState("");
  const [customer, setCustomer] = useState("");
  const [who, setWho] = useState(defaultWho);
  const [destFolder, setDestFolder] = useState(root);
  // Picking a source moves the destination folder to sit beside it, but
  // only until someone sets the folder themselves -- silently relocating a
  // folder the user typed is how a spec lands somewhere nobody looks.
  const [folderTouched, setFolderTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const term = sourceQuery.trim().toLowerCase();
  const matches = useMemo(
    () =>
      term
        ? supported.filter((e) =>
            [e.spec_number, e.customer, fileName(e.path), relativeFolder(root, e.path)].some((f) =>
              (f ?? "").toLowerCase().includes(term),
            ),
          )
        : supported,
    [supported, term, root],
  );

  const selected = useMemo(
    () => supported.find((e) => e.path === sourcePath) ?? null,
    [supported, sourcePath],
  );
  // A selection the current search has scrolled out of view is still a
  // selection. The old picker dropped it instead and refused at the final
  // click, with the list still showing a highlighted row.
  const selectedHidden = selected !== null && !matches.some((e) => e.path === selected.path);

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: matches.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 8,
  });

  function pick(entry: VaultEntry) {
    setSourcePath(entry.path);
    if (!folderTouched) setDestFolder(dirOf(entry.path));
  }

  // Type to narrow, arrow to choose: the whole interaction without leaving
  // the search box, which is where a search-then-pick list is actually used.
  function moveSelection(delta: number) {
    if (matches.length === 0) return;
    const current = matches.findIndex((e) => e.path === sourcePath);
    const next =
      current < 0
        ? delta > 0
          ? 0
          : matches.length - 1
        : Math.min(matches.length - 1, Math.max(0, current + delta));
    pick(matches[next]);
    virtualizer.scrollToIndex(next);
  }

  const trimmedNumber = specNumber.trim();
  const separator = destFolder.includes("\\") && !destFolder.includes("/") ? "\\" : "/";
  const destPath = `${destFolder.replace(/[/\\]+$/, "")}${separator}${trimmedNumber}.docx`;

  // The guardrail. A spec number is the document's identity, so two specs
  // answering to one number is a problem that costs nothing to prevent here
  // and a great deal to unpick later. Scoped to the open folder and
  // everything under it -- the scope the app was pointed at.
  //
  // Checked again on the server, which is the authority: this copy of the
  // index can be seconds stale, and two people creating the same number at
  // the same moment would both see a clear field.
  const numberConflicts = useMemo(() => {
    const wanted = normalizeSpecNumber(trimmedNumber);
    if (!wanted) return [];
    return supported.filter((e) => normalizeSpecNumber(e.spec_number) === wanted);
  }, [supported, trimmedNumber]);

  const pathConflict = useMemo(
    () => (trimmedNumber ? (entries.find((e) => samePath(e.path, destPath)) ?? null) : null),
    [entries, destPath, trimmedNumber],
  );

  const blocked =
    numberConflicts.length > 0 ||
    pathConflict !== null ||
    !trimmedNumber ||
    !customer.trim() ||
    !who.trim() ||
    (mode === "duplicate" && selected === null);

  async function submit() {
    if (!trimmedNumber || !customer.trim() || !who.trim()) {
      setError("Spec #, Customer, and your name are all required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "duplicate") {
        if (!selected) {
          setError("Choose a spec to duplicate from the list.");
          setBusy(false);
          return;
        }
        await duplicateSpec(selected.path, destPath, trimmedNumber, customer.trim(), who.trim());
      } else {
        await createBlankSpec(destPath, trimmedNumber, customer.trim(), who.trim());
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
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>New Spec</h2>

        <div className="mode-toggle">
          <button
            className={mode === "duplicate" ? "active" : ""}
            onClick={() => setMode("duplicate")}
            disabled={supported.length === 0}
          >
            Duplicate existing
          </button>
          <button className={mode === "blank" ? "active" : ""} onClick={() => setMode("blank")}>
            Blank template
          </button>
        </div>

        {mode === "duplicate" && (
          <div className="modal-field">
            Duplicate from
            <input
              className="source-search"
              value={sourceQuery}
              onChange={(e) => setSourceQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  moveSelection(1);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  moveSelection(-1);
                }
              }}
              placeholder="Search spec #, customer, file or folder…"
            />
            {/* Fits its contents up to a ceiling. A fixed-height box holding
                two matches reads as broken, and one that grows without limit
                pushes the fields below it off the screen. */}
            <div
              className="source-list"
              ref={scrollRef}
              role="listbox"
              aria-label="Spec to duplicate"
              style={{ height: Math.min(LIST_MAX_HEIGHT, Math.max(LIST_MIN_HEIGHT, virtualizer.getTotalSize())) }}
            >
              <div style={{ position: "relative", height: virtualizer.getTotalSize(), width: "100%" }}>
                {virtualizer.getVirtualItems().map((vi) => {
                  const entry = matches[vi.index];
                  const isSelected = entry.path === sourcePath;
                  const folder = relativeFolder(root, entry.path);
                  return (
                    <button
                      key={entry.path}
                      ref={virtualizer.measureElement}
                      data-index={vi.index}
                      data-source-path={entry.path}
                      role="option"
                      aria-selected={isSelected}
                      className={`source-option ${isSelected ? "selected" : ""}`}
                      style={{ transform: `translateY(${vi.start}px)` }}
                      onClick={() => pick(entry)}
                    >
                      <span className="source-option-main">
                        <span className="source-option-number">{entry.spec_number || fileName(entry.path)}</span>
                        <span className="source-option-customer">{entry.customer}</span>
                      </span>
                      {/* Two specs can share a number across customers, so the
                          folder is what tells them apart -- without it the
                          picker offers two identical-looking rows. */}
                      <span className="source-option-folder" title={entry.path}>
                        {folder || fileName(entry.path)}
                      </span>
                    </button>
                  );
                })}
              </div>
              {matches.length === 0 && <div className="source-empty">No spec matches “{sourceQuery.trim()}”.</div>}
            </div>
            <span className="modal-hint">
              {selected ? (
                <>
                  <strong>Copying {selected.spec_number || fileName(selected.path)}</strong>
                  {selected.customer ? ` — ${selected.customer}` : ""} from{" "}
                  {relativeFolder(root, selected.path) || "the vault root"}.
                  {selectedHidden && " (Not in the current search.)"}
                </>
              ) : (
                <>Pick the spec to copy. {supported.length} to choose from.</>
              )}{" "}
              Data tables carry over as a starting point; Spec #, Customer, and Revision History reset.
            </span>
          </div>
        )}

        <label className="modal-field">
          New Spec #
          <input
            value={specNumber}
            onChange={(e) => setSpecNumber(e.target.value)}
            placeholder="e.g. EG1600"
            aria-invalid={numberConflicts.length > 0}
            className={numberConflicts.length > 0 ? "conflict" : ""}
          />
          {numberConflicts.length > 0 && (
            <span className="modal-conflict">
              <strong>{trimmedNumber}</strong> is already used in this folder by{" "}
              {numberConflicts
                .slice(0, 3)
                .map((e) => `${fileName(e.path)} (${relativeFolder(root, e.path) || "vault root"})`)
                .join(", ")}
              {numberConflicts.length > 3 ? `, and ${numberConflicts.length - 3} more` : ""}. Choose a
              different number, or open that spec if you meant to revise it.
            </span>
          )}
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
          <input
            value={destFolder}
            onChange={(e) => {
              setFolderTouched(true);
              setDestFolder(e.target.value);
            }}
          />
          {pathConflict ? (
            <span className="modal-conflict">
              A file called {fileName(destPath)} is already in that folder. Nothing will be
              overwritten — change the number or the folder.
            </span>
          ) : (
            <span className="modal-hint">
              File will be created as {destFolder.replace(/[/\\]+$/, "")}
              {separator}
              {trimmedNumber || "<Spec #>"}.docx
            </span>
          )}
        </label>

        {error && <div className="error">{error}</div>}

        <div className="modal-actions">
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" onClick={submit} disabled={busy || blocked}>
            {busy ? "Creating…" : "Create Spec"}
          </button>
        </div>
      </div>
    </div>
  );
}
