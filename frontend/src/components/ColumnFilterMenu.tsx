import { useMemo, useState } from "react";

interface Props {
  distinctValues: string[];
  selected: Set<string> | null; // null = no filter (everything shown)
  formatLabel?: (value: string) => string;
  onApply: (selected: Set<string> | null) => void;
  onClose: () => void;
}

export default function ColumnFilterMenu({ distinctValues, selected, formatLabel, onApply, onClose }: Props) {
  const label = formatLabel ?? ((v: string) => v);
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(() => new Set(selected ?? distinctValues));

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return distinctValues;
    return distinctValues.filter((v) => v.toLowerCase().includes(term));
  }, [distinctValues, search]);

  function toggle(value: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  function selectAllVisible() {
    setChecked((prev) => new Set([...prev, ...visible]));
  }

  function clearAllVisible() {
    setChecked((prev) => {
      const next = new Set(prev);
      for (const v of visible) next.delete(v);
      return next;
    });
  }

  function apply() {
    // Every distinct value checked is equivalent to "no filter" -- store
    // null rather than a full set so an unrelated new value added later
    // (a spec created after this filter was set) doesn't get hidden.
    onApply(checked.size === distinctValues.length ? null : new Set(checked));
    onClose();
  }

  return (
    <div className="filter-menu" onClick={(e) => e.stopPropagation()}>
      <input
        className="filter-menu-search"
        placeholder="Search values…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        autoFocus
      />
      <div className="filter-menu-actions">
        <button onClick={selectAllVisible}>Select all</button>
        <button onClick={clearAllVisible}>Clear</button>
      </div>
      <div className="filter-menu-list">
        {visible.map((value) => (
          <label key={value} className="filter-menu-item">
            <input type="checkbox" checked={checked.has(value)} onChange={() => toggle(value)} />
            <span>{label(value) || "(blank)"}</span>
          </label>
        ))}
        {visible.length === 0 && <div className="filter-menu-empty">No matching values.</div>}
      </div>
      <div className="filter-menu-footer">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" onClick={apply}>
          Apply
        </button>
      </div>
    </div>
  );
}
