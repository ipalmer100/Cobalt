import { useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onNewSpec: () => void;
  onChangeFolder: () => void;
}

const ROW_HEIGHT_ESTIMATE = 52;
// Matches vault.py's _CONVERTING_MESSAGE -- a legacy .doc file is
// auto-converted to .docx in the background as soon as the vault sees it
// (no click needed), and shows this transient status until then.
const CONVERTING_MESSAGE = "Converting to .docx…";

const MAX_STATUS_LENGTH = 60;

function truncate(text: string): string {
  return text.length > MAX_STATUS_LENGTH ? text.slice(0, MAX_STATUS_LENGTH - 1) + "…" : text;
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

// The folder a spec sits in, relative to the vault root. Shown because a
// library organised by customer routinely holds same-named files in
// different folders -- without this, two specs look identical in the list.
function relativeFolder(root: string, path: string): string {
  const normRoot = root.replace(/[\\/]+$/, "");
  const rest = path.startsWith(normRoot) ? path.slice(normRoot.length) : path;
  const parts = rest.split(/[\\/]/).filter(Boolean);
  parts.pop(); // drop the filename
  return parts.join(" / ");
}

export default function Sidebar({ root, entries, selectedPath, onSelect, onNewSpec, onChangeFolder }: Props) {
  // A vault can have thousands of entries -- sorting with localeCompare on
  // every render (not just when entries actually change) was measurable at
  // that scale, on top of rendering every single one as a real DOM node
  // unconditionally (fixed below via virtualization, the bigger cost of
  // the two: thousands of always-mounted buttons made the sidebar visibly
  // slow to render and scroll).
  const sorted = useMemo(
    () => [...entries].sort((a, b) => fileName(a.path).localeCompare(fileName(b.path))),
    [entries],
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 12,
  });

  return (
    <div className="sidebar">
      <div className="sidebar-root">
        <span className="sidebar-root-path" title={root}>
          {root}
        </span>
        <button className="change-folder-button" onClick={onChangeFolder} title="Open a different folder">
          Change
        </button>
      </div>
      <button className="new-spec-button" onClick={onNewSpec}>
        + New Spec
      </button>
      <div className="sidebar-list" ref={scrollRef}>
        <div style={{ position: "relative", height: virtualizer.getTotalSize(), width: "100%" }}>
          {virtualizer.getVirtualItems().map((vi) => {
            const entry = sorted[vi.index];
            const isPending = entry.error === CONVERTING_MESSAGE;
            const folder = relativeFolder(root, entry.path);
            return (
              <button
                key={entry.path}
                ref={virtualizer.measureElement}
                data-index={vi.index}
                className={`sidebar-item ${entry.path === selectedPath ? "selected" : ""} ${
                  !entry.supported ? "unsupported" : ""
                }`}
                style={{ transform: `translateY(${vi.start}px)` }}
                onClick={() => onSelect(entry.path)}
                title={entry.error ?? entry.path}
              >
                <span className="sidebar-item-name">{fileName(entry.path)}</span>
                {folder && (
                  <span className="sidebar-item-folder" title={entry.path}>
                    {folder}
                  </span>
                )}
                {entry.supported ? (
                  <span className="sidebar-item-meta">
                    {entry.spec_number} · Rev {entry.revision_number}
                  </span>
                ) : (
                  <span className={`sidebar-item-meta ${isPending ? "pending" : "error"}`}>
                    {entry.error ? truncate(entry.error) : "unreadable"}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {sorted.length === 0 && <div className="sidebar-empty">No spec files found in this folder.</div>}
      </div>
    </div>
  );
}
