import { useEffect, useState } from "react";
import { connectLiveUpdates, getSpec, listVault, listViews, openVault } from "./api";
import Sidebar from "./components/Sidebar";
import SpecDetail from "./components/SpecDetail";
import MassEditGrid from "./components/MassEditGrid";
import type { SpecDetail as SpecDetailType, VaultEntry } from "./types";
import "./App.css";

type Mode = "detail" | "mass-edit";

export default function App() {
  const [root, setRoot] = useState("");
  const [rootInput, setRootInput] = useState("");
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [spec, setSpec] = useState<SpecDetailType | null>(null);
  const [mode, setMode] = useState<Mode>("detail");
  const [views, setViews] = useState<string[]>([]);
  const [readonlyColumns, setReadonlyColumns] = useState<string[]>([]);
  const [selectedView, setSelectedView] = useState<string>("Bill of Materials");
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  async function refreshVaultList() {
    try {
      const res = await listVault();
      setEntries(res.entries);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleOpen() {
    if (!rootInput.trim()) return;
    setOpening(true);
    setError(null);
    try {
      const res = await openVault(rootInput.trim());
      setRoot(res.root);
      const viewsRes = await listViews();
      await refreshVaultList();
      setViews(viewsRes.views);
      setReadonlyColumns(viewsRes.readonly_columns);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setOpening(false);
    }
  }

  useEffect(() => {
    if (!root) return;
    const disconnect = connectLiveUpdates(() => {
      // Instant reflect: any change on disk (ours or an external Word edit)
      // refreshes the file list and whatever is currently open.
      refreshVaultList();
      setRefreshToken((t) => t + 1);
    });
    return disconnect;
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
        <p>Point this at the folder containing your customer spec .docx files.</p>
        <div className="open-vault-form">
          <input
            placeholder="/path/to/specs"
            value={rootInput}
            onChange={(e) => setRootInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleOpen()}
          />
          <button disabled={opening} onClick={handleOpen}>
            {opening ? "Opening…" : "Open Vault"}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar root={root} entries={entries} selectedPath={selectedPath} onSelect={setSelectedPath} />
      <div className="main-panel">
        <div className="mode-tabs">
          <button className={mode === "detail" ? "active" : ""} onClick={() => setMode("detail")}>
            Spec Detail
          </button>
          <button className={mode === "mass-edit" ? "active" : ""} onClick={() => setMode("mass-edit")}>
            Mass Edit
          </button>
          {mode === "mass-edit" && (
            <select value={selectedView} onChange={(e) => setSelectedView(e.target.value)}>
              {views.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          )}
        </div>

        {error && <div className="error banner">{error}</div>}

        {mode === "detail" &&
          (spec ? (
            <SpecDetail spec={spec} onChanged={() => setRefreshToken((t) => t + 1)} />
          ) : (
            <div className="empty-state">Select a spec from the sidebar.</div>
          ))}

        {mode === "mass-edit" && (
          <MassEditGrid section={selectedView} readonlyColumns={readonlyColumns} refreshToken={refreshToken} />
        )}
      </div>
    </div>
  );
}
