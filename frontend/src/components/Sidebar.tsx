import type { VaultEntry } from "../types";

interface Props {
  root: string;
  entries: VaultEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export default function Sidebar({ root, entries, selectedPath, onSelect }: Props) {
  const sorted = [...entries].sort((a, b) => fileName(a.path).localeCompare(fileName(b.path)));

  return (
    <div className="sidebar">
      <div className="sidebar-root" title={root}>
        {root}
      </div>
      <div className="sidebar-list">
        {sorted.map((entry) => (
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
            ) : (
              <span className="sidebar-item-meta error">unreadable</span>
            )}
          </button>
        ))}
        {sorted.length === 0 && <div className="sidebar-empty">No spec files found in this folder.</div>}
      </div>
    </div>
  );
}
