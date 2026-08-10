import { useEffect, useRef, useState } from "react";
import { connectLiveUpdates, getExceptions, getSpec, listVault, listViews, openVault } from "./api";
import Sidebar from "./components/Sidebar";
import SpecDetail from "./components/SpecDetail";
import MassEditGrid from "./components/MassEditGrid";
import NewSpecModal from "./components/NewSpecModal";
import AuditLogView from "./components/AuditLogView";
import FolderPicker from "./components/FolderPicker";
import ExceptionsView from "./components/ExceptionsView";
import type { SpecDetail as SpecDetailType, VaultEntry, ViewMeta } from "./types";
import "./App.css";

type Mode = "detail" | "mass-edit" | "audit-log" | "exceptions";

const WHO_STORAGE_KEY = "specwrite.who";
// The vault folder is remembered so a daily user doesn't retype a long
// SharePoint path on every launch. Deliberately prefilled rather than
// auto-opened: indexing a large library takes real time, so opening it
// stays an explicit click.
const ROOT_STORAGE_KEY = "specwrite.lastRoot";
const RECENT_ROOTS_KEY = "specwrite.recentRoots";
const MAX_RECENT_ROOTS = 5;

function loadRecentRoots(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_ROOTS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((r) => typeof r === "string") : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [root, setRoot] = useState("");
  const [rootInput, setRootInput] = useState(() => localStorage.getItem(ROOT_STORAGE_KEY) ?? "");
  const [recentRoots, setRecentRoots] = useState<string[]>(loadRecentRoots);
  const [showPicker, setShowPicker] = useState(false);
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [spec, setSpec] = useState<SpecDetailType | null>(null);
  const [mode, setMode] = useState<Mode>("detail");
  const [views, setViews] = useState<string[]>([]);
  const [viewsMeta, setViewsMeta] = useState<Record<string, ViewMeta>>({});
  const [selectedView, setSelectedView] = useState<string>("Bill of Materials");
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [showNewSpec, setShowNewSpec] = useState(false);
  const [who, setWho] = useState(() => localStorage.getItem(WHO_STORAGE_KEY) ?? "");
  const [pendingExceptions, setPendingExceptions] = useState(0);

  function updateWho(value: string) {
    setWho(value);
    localStorage.setItem(WHO_STORAGE_KEY, value);
  }

  async function refreshExceptionCount() {
    try {
      const res = await getExceptions();
      setPendingExceptions(res.pending.length);
    } catch {
      // a vault that isn't open yet simply has nothing to triage
      setPendingExceptions(0);
    }
  }

  async function refreshVaultList() {
    try {
      const res = await listVault();
      setEntries(res.entries);
      refreshExceptionCount();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function rememberRoot(resolved: string) {
    localStorage.setItem(ROOT_STORAGE_KEY, resolved);
    setRecentRoots((prev) => {
      const next = [resolved, ...prev.filter((r) => r !== resolved)].slice(0, MAX_RECENT_ROOTS);
      localStorage.setItem(RECENT_ROOTS_KEY, JSON.stringify(next));
      return next;
    });
  }

  async function handleOpen(pathOverride?: string) {
    const target = (pathOverride ?? rootInput).trim();
    if (!target) return;
    setOpening(true);
    setError(null);
    try {
      const res = await openVault(target);
      setRoot(res.root);
      // Store the path the backend resolved, not what was typed, so the
      // remembered entry is canonical.
      rememberRoot(res.root);
      setRootInput(res.root);
      const viewsRes = await listViews();
      await refreshVaultList();
      setViews(viewsRes.views);
      setViewsMeta(viewsRes.views_meta);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setOpening(false);
    }
  }

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!root) return;
    const disconnect = connectLiveUpdates(() => {
      // A single batch write (e.g. a fill-handle drag spanning several
      // files) broadcasts one "changed" event per touched file. Reacting
      // to each individually would refetch the whole current view once
      // per file even though our own optimistic update already applied --
      // coalesce a burst into a single refresh instead.
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        refreshVaultList();
        setRefreshToken((t) => t + 1);
      }, 150);
    });
    return () => {
      disconnect();
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root]);

  useEffect(() => {
    if (!selectedPath) {
      setSpec(null);
      return;
    }
    getSpec(selectedPath)
      .then(setSpec)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [selectedPath, refreshToken]);

  if (!root) {
    return (
      <div className="open-vault-screen">
        <h1>SpecWrite</h1>
        <p>Point this at the folder containing your customer specs.</p>
        <p className="open-vault-sub">
          Subfolders are included, so one pick covers a whole library.
        </p>
        <div className="open-vault-form">
          <input
            placeholder="/path/to/specs"
            value={rootInput}
            onChange={(e) => setRootInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleOpen()}
          />
          <button className="secondary" disabled={opening} onClick={() => setShowPicker(true)}>
            Browse…
          </button>
          <button disabled={opening} onClick={() => handleOpen()}>
            {opening ? "Opening…" : "Open Vault"}
          </button>
        </div>

        {recentRoots.length > 0 && (
          <div className="recent-roots">
            <span className="recent-roots-label">Recent</span>
            {recentRoots.map((r) => (
              <button key={r} className="recent-root" title={r} disabled={opening} onClick={() => handleOpen(r)}>
                {r}
              </button>
            ))}
          </div>
        )}

        {error && <div className="error">{error}</div>}

        {showPicker && (
          <FolderPicker
            initialPath={rootInput || recentRoots[0]}
            onClose={() => setShowPicker(false)}
            onPick={(picked) => {
              setShowPicker(false);
              setRootInput(picked);
              handleOpen(picked);
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        root={root}
        entries={entries}
        selectedPath={selectedPath}
        onSelect={setSelectedPath}
        onNewSpec={() => setShowNewSpec(true)}
        onChangeFolder={() => {
          setRoot("");
          setSelectedPath(null);
          setSpec(null);
        }}
      />
      {showNewSpec && (
        <NewSpecModal
          root={root}
          entries={entries}
          defaultWho={who}
          onClose={() => setShowNewSpec(false)}
          onCreated={(path) => {
            setShowNewSpec(false);
            refreshVaultList();
            setSelectedPath(path);
            setMode("detail");
          }}
        />
      )}
      <div className="main-panel">
        <div className="mode-tabs">
          <button className={mode === "detail" ? "active" : ""} onClick={() => setMode("detail")}>
            Spec Detail
          </button>
          <button className={mode === "mass-edit" ? "active" : ""} onClick={() => setMode("mass-edit")}>
            Mass Edit
          </button>
          <button className={mode === "audit-log" ? "active" : ""} onClick={() => setMode("audit-log")}>
            Audit Log
          </button>
          <button
            className={mode === "exceptions" ? "active" : ""}
            onClick={() => setMode("exceptions")}
            title="Tables that need a human to say which section they belong to"
          >
            Exceptions
            {pendingExceptions > 0 && <span className="tab-badge">{pendingExceptions}</span>}
          </button>
          {mode === "mass-edit" && (
            <select value={selectedView} onChange={(e) => setSelectedView(e.target.value)}>
              {views.map((v) => (
                <option key={v} value={v}>
                  {v}
                  {viewsMeta[v] && !viewsMeta[v].editable ? " (read-only)" : ""}
                </option>
              ))}
            </select>
          )}
          <input
            className="who-input"
            placeholder="Your name (for the audit log)"
            value={who}
            onChange={(e) => updateWho(e.target.value)}
          />
        </div>

        {error && <div className="error banner">{error}</div>}

        {mode === "detail" &&
          (spec ? (
            <SpecDetail spec={spec} onChanged={() => setRefreshToken((t) => t + 1)} defaultWho={who} />
          ) : (
            <div className="empty-state">Select a spec from the sidebar.</div>
          ))}

        {mode === "mass-edit" && <MassEditGrid section={selectedView} refreshToken={refreshToken} who={who} />}

        {mode === "audit-log" && <AuditLogView refreshToken={refreshToken} />}

        {mode === "exceptions" && (
          <ExceptionsView
            refreshToken={refreshToken}
            who={who}
            onResolved={() => {
              refreshVaultList();
              setRefreshToken((t) => t + 1);
            }}
          />
        )}
      </div>
    </div>
  );
}
