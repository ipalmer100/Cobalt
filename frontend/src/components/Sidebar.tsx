import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { convertDoc } from "../api";
import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onNewSpec: () => void;
}

const ROW_HEIGHT_ESTIMATE = 52;

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export default function Sidebar({ root, entries, selectedPath, onSelect, onNewSpec }: Props) {
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
  const [converting, setConverting] = useState<string | null>(null);
  const [convertError, setConvertError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 12,
  });

  async function handleConvert(path: string, e: React.MouseEvent) {
    e.stopPropagation();
    setConverting(path);
    setConvertError(null);
    try {
      await convertDoc(path);
    } catch (err) {
      setConvertError(err instanceof Error ? err.message : String(err));
    } finally {
      setConverting(null);
    }
  }

  return (
    <div className="sidebar">
      <div className="sidebar-root" title={root}>
        {root}
      </div>
      <button className="new-spec-button" onClick={onNewSpec}>
        + New Spec
      </button>
      {convertError && <div className="error sidebar-error">{convertError}</div>}
      <div className="sidebar-list" ref={scrollRef}>
        <div style={{ position: "relative", height: virtualizer.getTotalSize(), width: "100%" }}>
          {virtualizer.getVirtualItems().map((vi) => {
            const entry = sorted[vi.index];
            const isLegacyDoc = !entry.supported && entry.path.toLowerCase().endsWith(".doc");
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
                {entry.supported ? (
                  <span className="sidebar-item-meta">
                    {entry.spec_number} · Rev {entry.revision_number}
                  </span>
                ) : isLegacyDoc ? (
                  <span className="sidebar-item-meta error">
                    legacy .doc —{" "}
                    <span className="convert-link" onClick={(e) => handleConvert(entry.path, e)}>
                      {converting === entry.path ? "converting…" : "convert to .docx"}
                    </span>
                  </span>
                ) : (
                  <span className="sidebar-item-meta error">unreadable</span>
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
