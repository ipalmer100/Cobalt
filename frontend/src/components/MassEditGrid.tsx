import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { commitEdits, getView } from "../api";
import type { BatchEditItem, ViewRow } from "../types";
import ColumnFilterMenu from "./ColumnFilterMenu";
import RevisionPrompt from "./RevisionPrompt";
import AutoTextarea from "./AutoTextarea";
import { passesStatus, type StatusFilter } from "../specStatus";

interface Props {
  section: string;
  refreshToken: number;
  who: string;
  // Set in the sidebar, applied here too: it filters the vault, not one
  // screen. Rows from a spec the filter excludes never reach the grid, so
  // a fill or a mass edit cannot touch a spec that is out of scope.
  status: StatusFilter;
  // Specs whose category Mass Edit does not cover. Stated rather than
  // silently omitted: a grid that quietly holds fewer specs than the vault
  // is a grid nobody can trust the row count of.
  excludedSpecs: number;
}

type SortDir = "asc" | "desc";
type DisplayItem = { type: "row"; row: ViewRow } | { type: "group-header"; key: string; count: number };

const META_PREFIX = ["Spec Number", "Customer"];
const ROW_HEIGHT_ESTIMATE = 30;

// Path relative to the vault root, so two same-named specs in different
// customer folders read differently in the File Path column. The stored
// value stays absolute -- it's the write key.
function relativeToRoot(root: string, path: string): string {
  if (!root) return fileName(path);
  const normRoot = root.replace(/[\\/]+$/, "");
  if (!path.startsWith(normRoot)) return fileName(path);
  return path.slice(normRoot.length).replace(/^[\\/]+/, "") || fileName(path);
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

// Includes table_index because a spec can hold several tables for one
// section (Duplex + Triplex Process Routing) -- without it their row 1s
// collide and an edit to one would patch/overwrite the other.
function rowKey(row: ViewRow): string {
  return `${row["File Path"]}|${row._source.section}|${row._source.table_index}|${row._source.row}`;
}

// Two specs describing the same business column rarely spell it the same
// way: one Bill of Materials says "Basis Wt Range", the next says "Basis Wt
// range"; a Physical Attributes header wraps "Basis Wt\n(#/ream)" where
// another puts it on one line. Matching on the raw string made those
// separate columns, so a spec's values landed under a heading no other spec
// shared -- and under the heading the grid *did* show, its cell was blank.
function normalizeColumn(name: string): string {
  return name.replace(/\s+/g, " ").trim().toLowerCase();
}

// Where a display column lives in one particular source table: `index` is
// the physical column a write must target, `label` the spelling that table
// actually uses (which is what a FIELDS write addresses by).
type ColumnRef = { index: number; label: string };

interface ColumnIndex {
  /** What the grid shows by default: columns most specs actually use. */
  columns: string[];
  /** Every column found anywhere, including the rare ones. */
  allColumns: string[];
  /** How many `allColumns` are held back from `columns`. */
  rareCount: number;
  /** Per row (keyed on its immutable _source), the layout of its table. */
  refs: WeakMap<object, Map<string, ColumnRef>>;
}

const EMPTY_INDEX: ColumnIndex = { columns: [], allColumns: [], rareCount: 0, refs: new WeakMap() };

function refFor(index: ColumnIndex, row: ViewRow, column: string): ColumnRef | undefined {
  return index.refs.get(row._source as unknown as object)?.get(normalizeColumn(column));
}

/** The value the grid shows, looked up through this row's own spelling. */
function cellText(row: ViewRow, column: string, index: ColumnIndex = EMPTY_INDEX): string {
  const direct = row[column];
  if (typeof direct === "string") return direct;
  const ref = refFor(index, row, column);
  return ref ? ((row[ref.label] as string) ?? "") : "";
}

/**
 * A column exists for a row only if that row's table has it *and* the row
 * physically reaches that far. Merged cells leave short rows, and a cell
 * that isn't in the document can't be written to -- rendering it as an
 * inviting empty editor is what let people type into nothing.
 */
function hasCell(row: ViewRow, column: string, index: ColumnIndex): boolean {
  if (column in row) return true;
  const ref = refFor(index, row, column);
  return ref != null && ref.label in row;
}

function displayLabel(column: string, value: string): string {
  return column === "File Path" ? fileName(value) : value || "";
}

// Excel-style: numeric-looking values sort numerically, everything else falls
// back to a locale/natural compare.
function compareValues(a: string, b: string): number {
  const an = parseFloat(a);
  const bn = parseFloat(b);
  const aIsNum = a.trim() !== "" && !Number.isNaN(an);
  const bIsNum = b.trim() !== "" && !Number.isNaN(bn);
  if (aIsNum && bIsNum) return an - bn;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

/**
 * Build the grid's column list, and for each row a map from column to where
 * that column sits in *its* table.
 *
 * This used to sample only the first five rows, on the assumption that every
 * row in a section shares one header. Real vaults don't: Hazelton's Bill of
 * Materials ends in "Designation", Franklin's in "Raw Material Item Code",
 * and one writes "Basis Wt Range" where the other writes "Basis Wt range".
 * Sampling five rows meant whichever spec happened to sort first defined the
 * columns for everyone: another spec's values had nowhere to appear (its
 * cells read blank even though the document had data), and typing into one
 * of those blanks threw "column not found" into a banner at the top of the
 * grid -- unread, hundreds of rows above where the person was working. It
 * read as "I typed a value and it didn't stick".
 *
 * So: scan every row, merge columns that differ only in case or whitespace,
 * and keep genuinely different headings as their own columns rather than
 * guessing they mean the same thing.
 *
 * Scanning everything brought its own problem at real scale, though. In a
 * few specs per thousand the parser locks onto a *data* row as the header,
 * so "PASS", "Every MR" and "On Floor, QC-SOP-052" arrived as column names,
 * alongside the "Column 2" and "Target (2)" placeholders that blank and
 * repeated headings produce. Ten real columns became twenty-four, and the
 * grid was unusable. So a column has to be one a reasonable share of specs
 * actually populates before it is shown by default; the rest stay
 * addressable and one click away rather than being dropped, because a
 * genuinely rare column is not the same thing as a misparse.
 *
 * Cost is one pass per *fetch*, not per render -- an edit patches row values
 * but never the table layouts, so the result is cached against the row's
 * `_source`, which patching preserves.
 */
function buildColumnIndex(rows: ViewRow[]): ColumnIndex {
  const trailing: string[] = [];
  if (rows.some((r) => "Variant" in r)) trailing.push("Variant");
  if (rows.some((r) => "Material Type" in r)) trailing.push("Material Type");
  trailing.push("File Path");
  const skip = new Set([...META_PREFIX, ...trailing, "_source"].map(normalizeColumn));

  const refs = new WeakMap<object, Map<string, ColumnRef>>();
  const byLayout = new Map<string, Map<string, ColumnRef>>();
  const display = new Map<string, string>();
  const order: string[] = [];
  // Which specs actually put a value in each column, and how many specs
  // there are to compare that against.
  const specsWithValue = new Map<string, Set<string>>();
  const allSpecs = new Set<string>();

  for (const row of rows) {
    const source = row._source as unknown as object;
    const path = row["File Path"] as string;
    allSpecs.add(path);

    const keys = row._source.header_row ?? Object.keys(row).filter((k) => k !== "_source");
    for (const label of keys) {
      const norm = normalizeColumn(label);
      if (skip.has(norm)) continue;
      // Presence isn't enough: a placeholder column that is blank in every
      // spec that nominally has it is exactly the noise being filtered.
      if (!(row[label] as string | undefined)?.trim()) continue;
      let carriers = specsWithValue.get(norm);
      if (!carriers) specsWithValue.set(norm, (carriers = new Set()));
      carriers.add(path);
    }

    if (refs.has(source)) continue;
    // JSON, not a join: a separator character could occur inside a
    // heading and make two different layouts look identical.
    const signature = JSON.stringify(keys);

    let layout = byLayout.get(signature);
    if (!layout) {
      layout = new Map<string, ColumnRef>();
      keys.forEach((label, index) => {
        const norm = normalizeColumn(label);
        // First position wins: a label repeated across a merged header spans
        // those columns, and the leftmost is the one to write.
        if (!layout!.has(norm)) layout!.set(norm, { index, label });
      });
      byLayout.set(signature, layout);
      for (const label of keys) {
        const norm = normalizeColumn(label);
        if (skip.has(norm) || display.has(norm)) continue;
        display.set(norm, label);
        order.push(norm);
      }
    }
    refs.set(source, layout);
  }

  // Which columns are real, and which are a misparsed spec's data.
  //
  // Measured against a 1,811-spec library rather than guessed. The two
  // populations separate cleanly there, but not where a first attempt at
  // this put the line: a column carried by a tenth of the specs. Real
  // columns from a minority template sit well under that -- "Feet /
  // Pallet" in 178 specs, "Melt Index" and "Density g/cm3" in 136,
  // "Designation" in 31 -- while the misparsed labels ("PASS", "--",
  // "Every MR", "Column 2") never exceed 8. A tenth would have hidden
  // every one of the real ones.
  //
  // So the line is a hundredth, which lands between the two, and nothing
  // is hidden at all below 25 specs: at that size every column is worth
  // seeing, and one spec with an unusual heading is not yet noise.
  const total = allSpecs.size;
  const minSpecs = total < 25 ? 0 : Math.max(2, Math.ceil(total * 0.01));
  const common = order.filter(
    // "Column 4" is not a column name -- it is what the parser writes when
    // the header cell is empty, so two specs' "Column 4" are not the same
    // column and counting them together says nothing. Never common, always
    // reachable through the rare-columns toggle.
    (norm) => !/^column \d+$/.test(norm) && (specsWithValue.get(norm)?.size ?? 0) >= minSpecs,
  );

  const dress = (names: string[]) => [...META_PREFIX, ...names.map((n) => display.get(n)!), ...trailing];
  return {
    columns: dress(common),
    allColumns: dress(order),
    rareCount: order.length - common.length,
    refs,
  };
}

interface DragState {
  column: string;
  sourceKey: string;
  sourceValue: string;
  startIndex: number;
  currentIndex: number;
}

export default function MassEditGrid({ section, refreshToken, who, status, excludedSpecs }: Props) {
  const [rows, setRows] = useState<ViewRow[]>([]);
  const [editable, setEditable] = useState(true);
  const [readonlyColumns, setReadonlyColumns] = useState<string[]>([]);
  const [root, setRoot] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Edits are held here, keyed by cell, and reach no document until the
  // revision describing them is written with them. `original` is kept so a
  // value typed back to what it was stops counting as a change.
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Map<string, { edit: BatchEditItem; original: string }>>(new Map());
  const [prompting, setPrompting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);
  // cellKey -> why that cell can't be staged, shown on the cell itself
  // rather than only in the banner above the grid.
  const [failedCells, setFailedCells] = useState<Map<string, string>>(new Map());

  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filters, setFilters] = useState<Record<string, Set<string>>>({});
  const [openFilterColumn, setOpenFilterColumn] = useState<string | null>(null);
  const [groupByColumn, setGroupByColumn] = useState<string | null>(null);
  const [showRareColumns, setShowRareColumns] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [activeCell, setActiveCell] = useState<{ key: string; column: string } | null>(null);
  const [dragging, setDragging] = useState<DragState | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await getView(section);
      setRows(res.rows);
      setEditable(res.editable);
      setReadonlyColumns(res.readonly_columns);
      setRoot(res.root ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // Switching to a different view means different columns/rows entirely,
  // so the old sort/filter/group-by wouldn't make sense anymore -- reset
  // it. But refreshToken alone (a websocket "changed" broadcast, which
  // fires for the user's own edit just as much as anyone else's) should
  // only reload this same view's row data, not blow away whatever
  // sort/filter/group-by the user currently has set.
  useEffect(() => {
    setSortColumn(null);
    setFilters({});
    setGroupByColumn(null);
    setCollapsedGroups(new Set());
    setShowRareColumns(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, refreshToken]);

  useEffect(() => {
    if (!openFilterColumn) return;
    const onDocClick = () => setOpenFilterColumn(null);
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [openFilterColumn]);

  // The Active/Inactive filter is applied before anything else, including
  // the column index -- a column that only the retired specs used should
  // not be offered while they are hidden.
  const inScopeRows = useMemo(
    () => rows.filter((row) => passesStatus(status, root, row["File Path"] as string)),
    [rows, status, root],
  );

  const columnIndex = useMemo(() => buildColumnIndex(inScopeRows), [inScopeRows]);
  const columns = showRareColumns ? columnIndex.allColumns : columnIndex.columns;

  // Excel's rule: each column's filter narrows what the others can see.
  // Filtering to one customer and then opening the Spec Number menu should
  // offer that customer's spec numbers, not all 1,739 in the vault --
  // otherwise the second filter is chosen against rows the first already
  // removed, and picking one silently empties the grid.
  const rowsPassingAllBut = useMemo(() => {
    const active = Object.entries(filters);
    return (except: string | null) =>
      active.length === 0
        ? inScopeRows
        : inScopeRows.filter((row) =>
            active.every(
              ([col, allowed]) => col === except || allowed.has(cellText(row, col, columnIndex)),
            ),
          );
  }, [inScopeRows, filters, columnIndex]);

  const filteredRows = useMemo(() => rowsPassingAllBut(null), [rowsPassingAllBut]);

  const sortedRows = useMemo(() => {
    if (!sortColumn) return filteredRows;
    const sorted = [...filteredRows].sort((a, b) => {
      const cmp = compareValues(cellText(a, sortColumn, columnIndex), cellText(b, sortColumn, columnIndex));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [filteredRows, sortColumn, sortDir, columnIndex]);

  const flatRowIndexByKey = useMemo(() => {
    const map = new Map<string, number>();
    sortedRows.forEach((row, i) => map.set(rowKey(row), i));
    return map;
  }, [sortedRows]);

  const displayItems = useMemo<DisplayItem[]>(() => {
    if (!groupByColumn) return sortedRows.map((row) => ({ type: "row", row }));
    const groups = new Map<string, ViewRow[]>();
    for (const row of sortedRows) {
      const key = cellText(row, groupByColumn, columnIndex);
      const bucket = groups.get(key);
      if (bucket) bucket.push(row);
      else groups.set(key, [row]);
    }
    const items: DisplayItem[] = [];
    for (const [key, groupRows] of groups) {
      items.push({ type: "group-header", key, count: groupRows.length });
      if (!collapsedGroups.has(key)) {
        for (const row of groupRows) items.push({ type: "row", row });
      }
    }
    return items;
  }, [sortedRows, groupByColumn, collapsedGroups, columnIndex]);

  // Everything the open column could still show, given every *other*
  // filter -- but not its own, so re-opening a filter you already set
  // still lists the values you unchecked and lets you put them back.
  const distinctValuesForOpenColumn = useMemo(() => {
    if (!openFilterColumn) return [];
    const set = new Set(
      rowsPassingAllBut(openFilterColumn).map((r) => cellText(r, openFilterColumn, columnIndex)),
    );
    return Array.from(set).sort((a, b) => compareValues(a, b));
  }, [rowsPassingAllBut, openFilterColumn, columnIndex]);

  const virtualizer = useVirtualizer({
    count: displayItems.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 12,
  });

  function clearFailure(cellKey: string) {
    setFailedCells((prev) => {
      if (!prev.has(cellKey)) return prev;
      const next = new Map(prev);
      next.delete(cellKey);
      return next;
    });
  }

  function draftKey(row: ViewRow, column: string): string {
    return `${rowKey(row)}:${column}`;
  }

  /**
   * Hold one cell's new value. Nothing is written -- staged edits travel to
   * the documents only when the revision describing them is saved with them.
   */
  function stageEdit(row: ViewRow, column: string, value: string) {
    const key = draftKey(row, column);
    const ref = refFor(columnIndex, row, column);
    const source = row._source;
    if (!ref) {
      setFailedCells((prev) =>
        new Map(prev).set(key, `This spec's ${source.section} table has no "${column}" column`),
      );
      return;
    }
    clearFailure(key);
    const original = cellText(row, column, columnIndex);
    const edit: BatchEditItem =
      source.kind === "record"
        ? {
            path: row["File Path"] as string,
            section: source.section,
            kind: "record",
            row: source.row,
            col: ref.index,
            value,
            table_index: source.table_index,
          }
        : {
            path: row["File Path"] as string,
            section: source.section,
            kind: "field",
            // A FIELDS table is addressed by its own label text, so send the
            // spelling this spec uses, not the heading the grid displays.
            label: ref.label,
            value,
            table_index: source.table_index,
          };
    setDrafts((prev) => {
      const next = new Map(prev);
      if (value === original) next.delete(key);
      else next.set(key, { edit, original });
      return next;
    });
  }

  /** Fill-handle drag: stages the same value down a column, still unwritten. */
  function stageFill(drag: DragState) {
    const lo = Math.min(drag.startIndex, drag.currentIndex);
    const hi = Math.max(drag.startIndex, drag.currentIndex);
    for (const row of sortedRows.slice(lo, hi + 1)) {
      if (rowKey(row) === drag.sourceKey) continue;
      // Skipped rather than guessed at: a spec whose table has no such
      // column simply isn't part of this fill.
      if (!refFor(columnIndex, row, drag.column)) continue;
      if (!hasCell(row, drag.column, columnIndex)) continue;
      stageEdit(row, drag.column, drag.sourceValue);
    }
  }

  function cancelEditing() {
    setEditing(false);
    setDrafts(new Map());
    setFailedCells(new Map());
    setError(null);
  }

  const pendingEdits = useMemo(
    () => [...drafts.values()].filter((d) => d.edit.value !== d.original).map((d) => d.edit),
    [drafts],
  );

  const affectedSpecCount = useMemo(
    () => new Set(pendingEdits.map((e) => e.path)).size,
    [pendingEdits],
  );

  async function commitDrafts(whoName: string, revisionText: string) {
    setCommitting(true);
    setPromptError(null);
    try {
      await commitEdits(pendingEdits, whoName, revisionText);
      setDrafts(new Map());
      setEditing(false);
      setPrompting(false);
      await load();
    } catch (e) {
      // Still only in the browser, so there is nothing to reconcile: stay
      // in edit mode with the drafts intact and let the user retry.
      setPromptError(e instanceof Error ? e.message : String(e));
    } finally {
      setCommitting(false);
    }
  }

  // Fill-handle drag: rAF-throttled so mousemove (which fires far faster
  // than a frame) doesn't trigger a state update -- and therefore a
  // re-render -- more than once per frame.
  useEffect(() => {
    if (!dragging) return;
    let raf = 0;
    let pending: MouseEvent | null = null;

    function process(e: MouseEvent) {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const tr = (el as HTMLElement | null)?.closest("tr[data-row-key]");
      const key = tr?.getAttribute("data-row-key");
      if (!key) return;
      const idx = flatRowIndexByKey.get(key);
      if (idx == null) return;
      setDragging((prev) => (prev ? { ...prev, currentIndex: idx } : prev));
    }

    function onMouseMove(e: MouseEvent) {
      pending = e;
      if (!raf) {
        raf = requestAnimationFrame(() => {
          raf = 0;
          if (pending) process(pending);
        });
      }
    }

    function onMouseUp() {
      if (raf) cancelAnimationFrame(raf);
      setDragging((current) => {
        if (current) stageFill(current);
        return null;
      });
    }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      if (raf) cancelAnimationFrame(raf);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging !== null, flatRowIndexByKey]);

  function toggleSort(column: string) {
    if (sortColumn !== column) {
      setSortColumn(column);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortColumn(null);
    }
  }

  function toggleGroupCollapsed(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Only while editing, and not while grouped (the drag range would jump
  // across group headers).
  const fillHandleEnabled = editing && !groupByColumn;
  const virtualItems = virtualizer.getVirtualItems();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom = virtualItems.length > 0 ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end : 0;

  return (
    <div className="mass-edit-grid">
      {loading && <div className="loading">Loading…</div>}
      {error && <div className="error">{error}</div>}
      {!editable && (
        <div className="warnings">
          Revision History is read-only here — it's the audit trail, so it only ever changes as
          a unit (new row + Revision # bump), through the revision you describe when saving.
        </div>
      )}

      <div className="grid-edit-bar">
        {!editing && editable && (
          <button className="primary" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {editing && (
          <>
            <span className="grid-dirty-count">
              {pendingEdits.length === 0
                ? "No changes yet"
                : `${pendingEdits.length} unsaved ${pendingEdits.length === 1 ? "change" : "changes"} across ` +
                  `${affectedSpecCount} ${affectedSpecCount === 1 ? "spec" : "specs"}`}
            </span>
            <button onClick={cancelEditing}>Cancel</button>
            <button
              className="primary"
              disabled={pendingEdits.length === 0}
              title={pendingEdits.length === 0 ? "Change something first" : undefined}
              onClick={() => {
                setPromptError(null);
                setPrompting(true);
              }}
            >
              Save…
            </button>
          </>
        )}
        <span className="grid-edit-hint">
          {editing
            ? "Changes are held here until you save. Every spec you touch gets the revision you describe."
            : editable
              ? "Read-only. Press Edit to make changes."
              : ""}
        </span>
      </div>

      <div className="grid-toolbar">
        <label>
          Group by:{" "}
          <select value={groupByColumn ?? ""} onChange={(e) => setGroupByColumn(e.target.value || null)}>
            <option value="">None</option>
            {columns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        {(sortColumn || Object.keys(filters).length > 0 || groupByColumn) && (
          <button
            className="grid-toolbar-reset"
            onClick={() => {
              setSortColumn(null);
              setFilters({});
              setGroupByColumn(null);
            }}
          >
            Reset view
          </button>
        )}
        {columnIndex.rareCount > 0 && (
          <label className="grid-rare-columns" title={
            showRareColumns
              ? "Hide columns only a few specs use"
              : "Headings only a handful of specs carry. Usually a mis-read header row, occasionally a real column one plant uses."
          }>
            <input
              type="checkbox"
              checked={showRareColumns}
              onChange={(e) => setShowRareColumns(e.target.checked)}
            />
            Show {columnIndex.rareCount} rare {columnIndex.rareCount === 1 ? "column" : "columns"}
          </label>
        )}
        {excludedSpecs > 0 && (
          <span
            className="grid-excluded-note"
            title="Blown Film specs are a different kind of document and are edited one at a time in Spec Detail"
          >
            {excludedSpecs} Blown Film {excludedSpecs === 1 ? "spec" : "specs"} not shown
          </span>
        )}
        <span className="grid-row-count">{sortedRows.length} rows</span>
      </div>

      <div className="mass-edit-scroll" ref={scrollRef}>
        <table className="records-table editable">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>
                  <div className="th-inner">
                    <span className="th-label" onClick={() => toggleSort(col)}>
                      {col}
                      {sortColumn === col ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                    </span>
                    <button
                      className={`th-filter-btn ${filters[col] ? "active" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenFilterColumn(openFilterColumn === col ? null : col);
                      }}
                      title="Filter"
                    >
                      ▾
                    </button>
                  </div>
                  {openFilterColumn === col && (
                    <ColumnFilterMenu
                      distinctValues={distinctValuesForOpenColumn}
                      selected={filters[col] ?? null}
                      formatLabel={(v) => displayLabel(col, v)}
                      onApply={(sel) =>
                        setFilters((prev) => {
                          const next = { ...prev };
                          if (sel) next[col] = sel;
                          else delete next[col];
                          return next;
                        })
                      }
                      onClose={() => setOpenFilterColumn(null)}
                    />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paddingTop > 0 && (
              <tr style={{ height: paddingTop }}>
                <td colSpan={columns.length} />
              </tr>
            )}
            {virtualItems.map((vi) => {
              const item = displayItems[vi.index];
              if (item.type === "group-header") {
                return (
                  <tr
                    key={`group:${item.key}`}
                    ref={virtualizer.measureElement}
                    data-index={vi.index}
                    className="group-header-row"
                    onClick={() => toggleGroupCollapsed(item.key)}
                  >
                    <td colSpan={columns.length}>
                      {collapsedGroups.has(item.key) ? "▸" : "▾"} {displayLabel(groupByColumn as string, item.key) || "(blank)"}{" "}
                      <span className="group-count">({item.count})</span>
                    </td>
                  </tr>
                );
              }
              const flatIndex = flatRowIndexByKey.get(rowKey(item.row)) ?? -1;
              return (
                <GridRow
                  key={rowKey(item.row)}
                  domIndex={vi.index}
                  flatIndex={flatIndex}
                  measureRef={virtualizer.measureElement}
                  row={item.row}
                  columns={columns}
                  root={root}
                  editable={editable}
                  readonlyColumns={readonlyColumns}
                  activeCell={activeCell}
                  dragging={dragging}
                  fillHandleEnabled={fillHandleEnabled}
                  editing={editing}
                  drafts={drafts}
                  failedCells={failedCells}
                  columnIndex={columnIndex}
                  onFocusCell={(column) => setActiveCell({ key: rowKey(item.row), column })}
                  onStageEdit={stageEdit}
                  onHandleMouseDown={(column, value) => {
                    setDragging({ column, sourceKey: rowKey(item.row), sourceValue: value, startIndex: flatIndex, currentIndex: flatIndex });
                  }}
                />
              );
            })}
            {paddingBottom > 0 && (
              <tr style={{ height: paddingBottom }}>
                <td colSpan={columns.length} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!loading && rows.length === 0 && <div className="empty">No rows found for this view.</div>}
      {!loading && rows.length > 0 && sortedRows.length === 0 && (
        <div className="empty">No rows match the current filters.</div>
      )}

      {prompting && (
        <RevisionPrompt
          editCount={pendingEdits.length}
          specSummary={`${affectedSpecCount} ${affectedSpecCount === 1 ? "spec" : "specs"}`}
          defaultWho={who}
          busy={committing}
          error={promptError}
          onCancel={() => setPrompting(false)}
          onConfirm={commitDrafts}
        />
      )}
    </div>
  );
}

interface GridRowProps {
  root: string;
  row: ViewRow;
  columns: string[];
  editable: boolean;
  readonlyColumns: string[];
  activeCell: { key: string; column: string } | null;
  dragging: DragState | null;
  fillHandleEnabled: boolean;
  editing: boolean;
  drafts: Map<string, { edit: BatchEditItem; original: string }>;
  failedCells: Map<string, string>;
  columnIndex: ColumnIndex;
  domIndex: number;
  flatIndex: number;
  measureRef: (el: HTMLElement | null) => void;
  onFocusCell: (column: string) => void;
  onStageEdit: (row: ViewRow, column: string, value: string) => void;
  onHandleMouseDown: (column: string, value: string) => void;
}

const GridRow = memo(function GridRow({
  row,
  columns,
  root,
  editable,
  readonlyColumns,
  activeCell,
  dragging,
  fillHandleEnabled,
  editing,
  drafts,
  failedCells,
  columnIndex,
  domIndex,
  flatIndex,
  measureRef,
  onFocusCell,
  onStageEdit,
  onHandleMouseDown,
}: GridRowProps) {
  const key = rowKey(row);
  const dragLo = dragging ? Math.min(dragging.startIndex, dragging.currentIndex) : -1;
  const dragHi = dragging ? Math.max(dragging.startIndex, dragging.currentIndex) : -1;
  const rowInDragRange = dragging != null && flatIndex >= dragLo && flatIndex <= dragHi;

  return (
    <tr key={key} ref={measureRef} data-index={domIndex} data-row-key={key}>
      {columns.map((col) => {
        // Not editing means not editable: the grid is a report until Edit
        // is pressed, which is what makes "no change without a revision"
        // something the UI enforces rather than merely asks for.
        const readOnly = !editing || !editable || readonlyColumns.includes(col);
        const staged = drafts.get(`${key}:${col}`);
        const stored = cellText(row, col, columnIndex);
        const value = staged?.edit.value ?? stored;
        if (col === "File Path") {
          return (
            <td key={col} title={value}>
              {relativeToRoot(root, value)}
            </td>
          );
        }
        if (readOnly) {
          return <td key={col}>{value}</td>;
        }
        // This spec's table simply doesn't have this column. Shown as a
        // struck-through gap rather than an empty editor, so nobody spends
        // their afternoon typing into a cell that cannot be saved.
        if (!hasCell(row, col, columnIndex)) {
          return (
            <td key={col} className="cell-absent" title={`This spec's ${row._source.section} table has no "${col}" column`} />
          );
        }
        const cellKey = `${key}:${col}`;
        const isActive = activeCell?.key === key && activeCell.column === col;
        const isDragSource = dragging?.sourceKey === key && dragging.column === col;
        const isFillPreview = dragging != null && dragging.column === col && rowInDragRange && !isDragSource;
        const dirty = staged != null && staged.edit.value !== staged.original;
        const failure = failedCells.get(cellKey);
        return (
          <td
            key={col}
            title={failure ?? (dirty ? `Unsaved. Was: ${staged!.original || "(blank)"}` : undefined)}
            className={`${dirty ? "cell-dirty" : ""} ${isActive ? "active-cell" : ""} ${isFillPreview ? "fill-preview" : ""} ${failure ? "save-failed" : ""}`}
            style={{ position: "relative" }}
            // The editor fills the cell, but a row is as tall as its
            // tallest cell -- so a one-line value in a row with a
            // five-line neighbour still leaves bare td underneath.
            // Clicking that used to do nothing, which read as the cell
            // only responding to its text. Anything that reaches the td
            // itself (not the editor, not the fill handle) focuses it.
            onClick={(e) => {
              if (e.target !== e.currentTarget) return;
              e.currentTarget.querySelector("textarea")?.focus();
            }}
          >
            <EditableCellInput
              value={value}
              onFocus={() => onFocusCell(col)}
              onCommit={(next) => onStageEdit(row, col, next)}
            />
            {isActive && fillHandleEnabled && (
              <div
                className="fill-handle"
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onHandleMouseDown(col, value);
                }}
              />
            )}
            {isDragSource && <div className="fill-source-outline" />}
          </td>
        );
      })}
    </tr>
  );
});

interface EditableCellInputProps {
  value: string;
  onFocus: () => void;
  onCommit: (value: string) => void;
}

// A plain uncontrolled <input defaultValue> never picks up a value change
// that comes from outside the DOM (fill-handle patching this exact cell,
// a websocket-driven refresh from an external Word edit, a filter/sort
// reorder revealing a row someone else just changed) -- React only applies
// defaultValue on first mount. This stays controlled but resyncs from the
// prop whenever it changes externally, without clobbering an in-progress
// keystroke (the effect only fires when `value` itself changes, not on
// every render).
// A <textarea>, not an <input>: real spec cells are routinely multi-line
// (a BOM "Raw Material" naming both sides of a film, a Slitting splice
// instruction, a customer address). An <input> silently drops the newlines
// the moment its value is set, so editing such a cell -- even fixing one
// typo -- used to collapse it to a single line and save that back over the
// document. Enter commits (matching the old single-line feel);
// Shift+Enter inserts a line break; Escape reverts.
function EditableCellInput({ value, onFocus, onCommit }: EditableCellInputProps) {
  const [local, setLocal] = useState(value);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const editing = useRef(false);

  useEffect(() => {
    // ...but not out from under someone who is mid-keystroke. Refreshes
    // arrive constantly (every save broadcasts, and the watcher re-indexes
    // again behind it), and resyncing while the cell has focus would erase
    // what is being typed just before it gets committed.
    if (editing.current) return;
    setLocal(value);
  }, [value]);

  return (
    <AutoTextarea
      textareaRef={(el) => {
        ref.current = el;
      }}
      className="cell-editor"
      value={local}
      onChange={(e) => {
        setLocal(e.target.value);
        // Staged as you type, not on blur. Nothing is written either way
        // now, and the unsaved-changes count and the dirty-cell marks are
        // the only evidence of what is pending -- they have to be live, or
        // the grid says "no changes yet" while you are typing into it.
        onCommit(e.target.value);
      }}
      onFocus={() => {
        editing.current = true;
        onFocus();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          ref.current?.blur();
        } else if (e.key === "Escape") {
          e.preventDefault();
          editing.current = false;
          setLocal(value);
          ref.current?.blur();
        }
      }}
      onBlur={() => {
        editing.current = false;
        if (local !== value) onCommit(local);
      }}
    />
  );
}
