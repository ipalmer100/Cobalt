import { useMemo, useRef, useState } from "react";

interface Props {
  distinctValues: string[];
  selected: Set<string> | null; // null = no filter (everything shown)
  formatLabel?: (value: string) => string;
  onApply: (selected: Set<string> | null) => void;
  onClose: () => void;
}

/**
 * Excel's AutoFilter menu, including the part people actually use: type in
 * the search box and press OK, and you get what you searched for.
 *
 * That case used to fail. Every value starts checked, so searching without
 * unchecking anything left everything checked, which was read as "no filter"
 * and cleared it -- searching for one customer showed all of them. Now a
 * search term narrows what Apply commits, exactly as Excel does: the
 * matching values become the filter, whether or not you touched a checkbox.
 */
export default function ColumnFilterMenu({ distinctValues, selected, formatLabel, onApply, onClose }: Props) {
  // Held in a ref so the memo below does not re-run on every render just
  // because the parent passed a fresh arrow function.
  const labelRef = useRef(formatLabel);
  labelRef.current = formatLabel;
  const label = (v: string) => (labelRef.current ? labelRef.current(v) : v);
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(() => new Set(selected ?? distinctValues));

  const searching = search.trim() !== "";

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return distinctValues;
    return distinctValues.filter((v) => label(v).toLowerCase().includes(term));
  }, [distinctValues, search]);

  // What Apply would commit right now. While searching, only the matches
  // count -- searching *is* the selection, which is why typing a term and
  // pressing Apply just works.
  const effective = useMemo(
    () => (searching ? visible.filter((v) => checked.has(v)) : distinctValues.filter((v) => checked.has(v))),
    [searching, visible, distinctValues, checked],
  );

  const allVisibleChecked = visible.length > 0 && visible.every((v) => checked.has(v));

  function toggle(value: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  function toggleAllVisible() {
    setChecked((prev) => {
      const next = new Set(prev);
      if (allVisibleChecked) for (const v of visible) next.delete(v);
      else for (const v of visible) next.add(v);
      return next;
    });
  }

  function apply() {
    if (effective.length === 0) return; // Excel won't let you hide every row
    // "Everything, with nothing searched" is genuinely no filter -- store
    // null so a value that appears later (a spec added after this filter
    // was set) isn't retroactively hidden by a frozen list.
    const isEverything = !searching && effective.length === distinctValues.length;
    onApply(isEverything ? null : new Set(effective));
    onClose();
  }

  return (
    <div className="filter-menu" onClick={(e) => e.stopPropagation()}>
      <input
        className="filter-menu-search"
        placeholder="Search…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            apply();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
        autoFocus
      />

      <label className="filter-menu-item filter-menu-all">
        <input type="checkbox" checked={allVisibleChecked} onChange={toggleAllVisible} />
        <span>{searching ? "Select all search results" : "Select all"}</span>
      </label>

      <div className="filter-menu-list">
        {visible.map((value) => (
          <label key={value} className="filter-menu-item">
            <input type="checkbox" checked={checked.has(value)} onChange={() => toggle(value)} />
            <span>{label(value) || "(blank)"}</span>
          </label>
        ))}
        {visible.length === 0 && <div className="filter-menu-empty">No matching values.</div>}
      </div>

      <div className="filter-menu-count">
        {effective.length} of {distinctValues.length} shown
      </div>

      <div className="filter-menu-footer">
        <button onClick={onClose}>Cancel</button>
        <button
          className="primary"
          onClick={apply}
          disabled={effective.length === 0}
          title={effective.length === 0 ? "Select at least one value" : undefined}
        >
          Apply
        </button>
      </div>
    </div>
  );
}
