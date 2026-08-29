import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { SpecCategory, VaultEntry } from "../types";
import { isInactive, type StatusFilter } from "../specStatus";
import { CATEGORY_LABELS, isMassEditable, type CategoryFilter } from "../specCategory";

interface Props {
  root: string;
  entries: VaultEntry[];
  selectedPath: string | null;
  status: StatusFilter;
  onStatusChange: (next: StatusFilter) => void;
  category: CategoryFilter;
  onCategoryChange: (next: CategoryFilter) => void;
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

export default function Sidebar({
  root,
  entries,
  selectedPath,
  status,
  onStatusChange,
  category,
  onCategoryChange,
  onSelect,
  onNewSpec,
  onChangeFolder,
}: Props) {
  // A vault can have thousands of entries -- sorting with localeCompare on
  // every render (not just when entries actually change) was measurable at
  // that scale, on top of rendering every single one as a real DOM node
  // unconditionally (fixed below via virtualization, the bigger cost of
  // the two: thousands of always-mounted buttons made the sidebar visibly
  // slow to render and scroll).
  const [query, setQuery] = useState("");
  // The Active/Inactive state lives in the app, not here: it filters the
  // mass-edit grid too, so a spec hidden in one place is hidden in both.
  const { showActive, showInactive } = status;

  const sorted = useMemo(
    () => [...entries].sort((a, b) => fileName(a.path).localeCompare(fileName(b.path))),
    [entries],
  );

  const inactiveCount = useMemo(
    () => sorted.filter((entry) => isInactive(root, entry.path)).length,
    [sorted, root],
  );

  // Counted once, so each choice can say how many specs it holds -- the
  // number is what makes the filter safe to use: you can see nothing has
  // gone missing, it has just moved.
  const categoryCounts = useMemo(() => {
    const counts = new Map<SpecCategory, number>();
    for (const entry of sorted) {
      if (!entry.category) continue;
      counts.set(entry.category, (counts.get(entry.category) ?? 0) + 1);
    }
    return counts;
  }, [sorted]);

  // Offered only when the vault actually holds more than one kind of spec.
  // A control that cannot change anything is noise in a narrow sidebar.
  const categories = useMemo(
    () => (Object.keys(CATEGORY_LABELS) as SpecCategory[]).filter((c) => (categoryCounts.get(c) ?? 0) > 0),
    [categoryCounts],
  );

  // Search spec number, customer, file name and folder together: people look
  // for a spec by whichever of those they happen to know.
  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return sorted.filter((entry) => {
      if (category !== "all" && entry.category !== category) return false;
      if (!(isInactive(root, entry.path) ? showInactive : showActive)) return false;
      if (!term) return true;
      return [entry.spec_number, entry.customer, fileName(entry.path), relativeFolder(root, entry.path)]
        .some((field) => (field ?? "").toLowerCase().includes(term));
    });
  }, [sorted, query, root, showActive, showInactive, category]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: filtered.length,
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
      <input
        className="sidebar-search"
        placeholder="Search spec # or customer…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {categories.length > 1 && (
        <div className="sidebar-category">
          <div className="sidebar-filter-label">Category</div>
          <div className="category-segmented" role="group" aria-label="Spec category">
            <button
              className={`category-option ${category === "all" ? "selected" : ""}`}
              onClick={() => onCategoryChange("all")}
              aria-pressed={category === "all"}
              title="Every spec in the vault"
            >
              <span className="category-option-name">All</span>
              <span className="category-option-count">{sorted.length}</span>
            </button>
            {categories.map((name) => (
              <button
                key={name}
                className={`category-option ${category === name ? "selected" : ""} category-${name}`}
                onClick={() => onCategoryChange(name)}
                aria-pressed={category === name}
                title={
                  isMassEditable(name)
                    ? `${CATEGORY_LABELS[name]} specs — Spec Detail and Mass Edit`
                    : `${CATEGORY_LABELS[name]} specs — Spec Detail only, not covered by Mass Edit`
                }
              >
                <span className="category-option-name">{CATEGORY_LABELS[name]}</span>
                <span className="category-option-count">{categoryCounts.get(name)}</span>
              </button>
            ))}
          </div>
          {!isMassEditable(category === "all" ? "standard" : category) && (
            <div className="category-note">Spec Detail only — no mass editing</div>
          )}
        </div>
      )}
      {inactiveCount > 0 && (
        <div className="sidebar-status-filter">
          <button
            className={`status-toggle ${showActive ? "on" : ""}`}
            onClick={() => onStatusChange({ showActive: !showActive, showInactive })}
            title="Specs outside an Inactive folder — applies to Mass Edit too"
          >
            Active <span className="status-count">{sorted.length - inactiveCount}</span>
          </button>
          <button
            className={`status-toggle ${showInactive ? "on" : ""}`}
            onClick={() => onStatusChange({ showActive, showInactive: !showInactive })}
            title="Specs filed under an Inactive Specifications folder — applies to Mass Edit too"
          >
            Inactive <span className="status-count">{inactiveCount}</span>
          </button>
        </div>
      )}
      {(query.trim() !== "" || !showActive || !showInactive || category !== "all") && (
        <div className="sidebar-search-count">
          {filtered.length} of {sorted.length}
        </div>
      )}
      <button className="new-spec-button" onClick={onNewSpec}>
        + New Spec
      </button>
      <div className="sidebar-list" ref={scrollRef}>
        <div style={{ position: "relative", height: virtualizer.getTotalSize(), width: "100%" }}>
          {virtualizer.getVirtualItems().map((vi) => {
            const entry = filtered[vi.index];
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
                <span className="sidebar-item-name">
                  {fileName(entry.path)}
                  {/* Marked on the row itself, not only in the filter: in a
                      mixed list you have to be able to tell which specs
                      Mass Edit will not cover without selecting them. */}
                  {entry.category && !isMassEditable(entry.category) && (
                    <span className={`category-tag category-${entry.category}`}>
                      {CATEGORY_LABELS[entry.category]}
                    </span>
                  )}
                </span>
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
