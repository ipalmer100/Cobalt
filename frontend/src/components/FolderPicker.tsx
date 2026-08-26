import { useEffect, useState } from "react";
import { browseFolders } from "../api";
import type { BrowseResponse } from "../types";

interface Props {
  initialPath?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}

/**
 * Folder picker served by the backend rather than the browser.
 *
 * The app opens in the user's default browser, and browsers deliberately
 * withhold real filesystem paths (`webkitdirectory` and
 * `showDirectoryPicker` both give you file handles, never a path) -- but
 * opening a vault needs a real path. So the directory listing comes from
 * the backend, which is running on the same machine as the files.
 */
export default function FolderPicker({ initialPath, onPick, onClose }: Props) {
  const [data, setData] = useState<BrowseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load(path?: string | null) {
    setLoading(true);
    setError(null);
    browseFolders(path ?? undefined)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load(initialPath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal folder-picker" onClick={(e) => e.stopPropagation()}>
        <h2>Choose the folder with your specs</h2>
        <p className="folder-picker-hint">
          Point this at your synced SharePoint library (or any folder). Specs in subfolders are
          included automatically.
        </p>

        <div className="folder-picker-bar">
          <div className="folder-picker-path">{data?.path ?? "This computer"}</div>
          {/* Asking with no path lands on the Desktop (the backend's
              default), so this is the way back after wandering off. */}
          <button className="folder-picker-home" onClick={() => load(undefined)}>
            Desktop
          </button>
        </div>
        {data?.path && (
          <div className="folder-picker-count">
            {data.spec_count > 0
              ? `${data.spec_count} spec${data.spec_count === 1 ? "" : "s"} directly in this folder`
              : "No specs directly in this folder (subfolders may still have them)"}
          </div>
        )}

        {error && <div className="error">{error}</div>}
        {loading && <div className="loading">Loading…</div>}

        <div className="folder-picker-list">
          {data?.parent && (
            <button className="folder-row up" onClick={() => load(data.parent)}>
              ⬆ ..
            </button>
          )}
          {data?.entries.map((entry) => (
            <button key={entry.path} className="folder-row" onClick={() => load(entry.path)}>
              📁 {entry.name}
            </button>
          ))}
          {!loading && data && data.entries.length === 0 && (
            <div className="empty">No subfolders here.</div>
          )}
        </div>

        <div className="modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            disabled={!data?.path}
            onClick={() => data?.path && onPick(data.path)}
          >
            Use this folder
          </button>
        </div>
      </div>
    </div>
  );
}
