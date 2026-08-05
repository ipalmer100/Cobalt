import { useState } from "react";
import { convertDoc } from "../api";
import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onNewSpec: () => void;
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export default function Sidebar({ root, entries, selectedPath, onSelect, onNewSpec }: Props) {
  const sorted = [...entries].sort((a, b) => fileName(a.path).localeCompare(fileName(b.path)));
  const [converting, setConverting] = useState<string | null>(null);
  const [convertError, setConvertError] = useState<string | null>(null);

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
      <div className="sidebar-list">
        {sorted.map((entry) => {
          const isLegacyDoc = !entry.supported && entry.path.toLowerCase().endsWith(".doc");
          return (
            <button
              key={entry.path}
              className={`sidebar-item ${entry.path === selectedPath ? "selected" : ""} ${
                !entry.supported ? "unsupported" : ""
              }`}
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
        {sorted.length === 0 && <div className="sidebar-empty">No spec files found in this folder.</div>}
      </div>
    </div>
  );
}
