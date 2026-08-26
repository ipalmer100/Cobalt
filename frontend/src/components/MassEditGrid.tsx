import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { getView, writeCell, writeCellsBatch, writeField } from "../api";
import type { BatchEditItem, ViewRow } from "../types";
import ColumnFilterMenu from "./ColumnFilterMenu";

interface Props {
  section: string;
  refreshToken: number;
  who: string;
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
  columns: string[];
  /** Per row (keyed on its immutable _source), the layout of its table. */
  refs: WeakMap<object, Map<string, ColumnRef>>;
}

const EMPTY_INDEX: ColumnIndex = { columns: [], refs: new WeakMap() };

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

  for (const row of rows) {
    const source = row._source as unknown as object;
    if (refs.has(source)) continue;
    const keys = row._source.header_row ?? Object.keys(row).filter((k) => k !== "_source");
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

  return { columns: [...META_PREFIX, ...order.map((n) => display.get(n)!), ...trailing], refs };
}

interface DragState {
  column: string;
  sourceKey: string;
  sourceValue: string;
  startIndex: number;
  currentIndex: number;
}

export default function MassEditGrid({ section, refreshToken, who }: Props) {
  const [rows, setRows] = useState<ViewRow[]>([]);
  const [editable, setEditable] = useState(true);
  const [readonlyColumns, setReadonlyColumns] = useState<string[]>([]);
  const [root, setRoot] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingKeys, setSavingKeys] = useState<Set<string>>(new Set());
  // cellKey -> why that cell's save failed, so the failure shows where it
  // happened instead of only in the banner above the grid.
  const [failedCells, setFailedCells] = useState<Map<string, string>>(new Map());

  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filters, setFilters] = useState<Record<string, Set<string>>>({});
  const [openFilterColumn, setOpenFilterColumn] = useState<string | null>(null);
  const [groupByColumn, setGroupByColumn] = useState<string | null>(null);
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

  const columnIndex = useMemo(() => buildColumnIndex(rows), [rows]);
  const columns = columnIndex.columns;

  const filteredRows = useMemo(() => {
    const active = Object.entries(filters);
    if (active.length === 0) return rows;
    return rows.filter((row) => active.every(([col, allowed]) => allowed.has(cellText(row, col, columnIndex))));
  }, [rows, filters, columnIndex]);

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

  const distinctValuesForOpenColumn = useMemo(() => {
    if (!openFilterColumn) return [];
    const set = new Set(rows.map((r) => cellText(r, openFilterColumn, columnIndex)));
    return Array.from(set).sort((a, b) => compareValues(a, b));
  }, [rows, openFilterColumn, columnIndex]);

  const virtualizer = useVirtualizer({
    count: displayItems.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_ESTIMATE,
    overscan: 12,
  });

  function patchRows(patches: Map<string, Record<string, string>>) {
    setRows((prev) => {
      const map = new Map(prev.map((r, i) => [rowKey(r), i]));
      const next = [...prev];
      for (const [key, changes] of patches) {
        const idx = map.get(key);
        if (idx != null) next[idx] = { ...next[idx], ...changes };
      }
      return next;
    });
  }

  function clearFailure(cellKey: string) {
    setFailedCells((prev) => {
      if (!prev.has(cellKey)) return prev;
      const next = new Map(prev);
      next.delete(cellKey);
      return next;
    });
  }

  async function commitEdit(row: ViewRow, column: string, value: string) {
    const key = rowKey(row);
    const cellKey = `${key}:${column}`;
    const source = row._source;
    const ref = refFor(columnIndex, row, column);
    setSavingKeys((prev) => new Set(prev).add(cellKey));
    clearFailure(cellKey);
    try {
      if (source.kind === "record") {
        if (!ref) throw new Error(`This spec's ${source.section} table has no "${column}" column`);
        await writeCell(row["File Path"] as string, source.section, source.row, ref.index, value, who, source.table_index);
      } else {
        // A FIELDS table is addressed by its own label text, so send the
        // spelling this spec uses, not the heading the grid displays.
        await writeField(row["File Path"] as string, source.section, ref?.label ?? column, value, who, source.table_index);
      }
      patchRows(new Map([[key, { [ref?.label ?? column]: value }]]));
    } catch (e) {
      // Marked on the cell itself, not only in the banner at the top of the
      // grid: when you are 300 rows down, a banner you can't see is
      // indistinguishable from the edit silently not saving.
      const message = e instanceof Error ? e.message : String(e);
      setFailedCells((prev) => new Map(prev).set(cellKey, message));
      setError(message);
    } finally {
      setSavingKeys((prev) => {
        const next = new Set(prev);
        next.delete(cellKey);
        return next;
      });
    }
  }

  async function commitFill(drag: DragState) {
    const lo = Math.min(drag.startIndex, drag.currentIndex);
    const hi = Math.max(drag.startIndex, drag.currentIndex);
    const targets = sortedRows.slice(lo, hi + 1).filter((r) => rowKey(r) !== drag.sourceKey);
    if (targets.length === 0) return;

    const edits: BatchEditItem[] = [];
    const patches = new Map<string, Record<string, string>>();
    for (const row of targets) {
      const source = row._source;
      const path = row["File Path"] as string;
      // Skipped rather than guessed at: a spec whose table has no such
      // column simply isn't part of this fill.
      const ref = refFor(columnIndex, row, drag.column);
      if (!ref) continue;
      if (source.kind === "record") {
        edits.push({
          path,
          section: source.section,
          kind: "record",
          row: source.row,
          col: ref.index,
          value: drag.sourceValue,
          table_index: source.table_index,
        });
      } else {
        edits.push({
          path,
          section: source.section,
          kind: "field",
          label: ref.label,
          value: drag.sourceValue,
          table_index: source.table_index,
        });
      }
      patches.set(rowKey(row), { [ref.label]: drag.sourceValue });
    }
    if (edits.length === 0) return;

    const cellKeys = Array.from(patches.keys()).map((k) => `${k}:${drag.column}`);
    setSavingKeys((prev) => new Set([...prev, ...cellKeys]));
    try {
      await writeCellsBatch(edits, who);
      patchRows(patches);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingKeys((prev) => {
        const next = new Set(prev);
        cellKeys.forEach((k) => next.delete(k));
        return next;
      });
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
        if (current) commitFill(current);
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

  const fillHandleEnabled = !groupByColumn;
  const virtualItems = virtualizer.getVirtualItems();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom = virtualItems.length > 0 ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end : 0;

  return (
    <div className="mass-edit-grid">
      {loading && <div className="loading">Loading…</div>}
      {error && <div className="error">{error}</div>}
      {!editable && (
        <div className="warnings">
          Revision History is read-only here — it's the audit trail, so it only changes as a
          unit (new row + Revision # bump) via "Add Revision" on each spec's detail view.
        </div>
      )}

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
                  savingKeys={savingKeys}
                  failedCells={failedCells}
                  columnIndex={columnIndex}
                  onFocusCell={(column) => setActiveCell({ key: rowKey(item.row), column })}
                  onCommitEdit={commitEdit}
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
  savingKeys: Set<string>;
  failedCells: Map<string, string>;
  columnIndex: ColumnIndex;
  domIndex: number;
  flatIndex: number;
  measureRef: (el: HTMLElement | null) => void;
  onFocusCell: (column: string) => void;
  onCommitEdit: (row: ViewRow, column: string, value: string) => void;
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
  savingKeys,
  failedCells,
  columnIndex,
  domIndex,
  flatIndex,
  measureRef,
  onFocusCell,
  onCommitEdit,
  onHandleMouseDown,
}: GridRowProps) {
  const key = rowKey(row);
  const dragLo = dragging ? Math.min(dragging.startIndex, dragging.currentIndex) : -1;
  const dragHi = dragging ? Math.max(dragging.startIndex, dragging.currentIndex) : -1;
  const rowInDragRange = dragging != null && flatIndex >= dragLo && flatIndex <= dragHi;

  return (
    <tr key={key} ref={measureRef} data-index={domIndex} data-row-key={key}>
      {columns.map((col) => {
        const readOnly = !editable || readonlyColumns.includes(col);
        const value = cellText(row, col, columnIndex);
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
        const isSaving = savingKeys.has(cellKey);
        const failure = failedCells.get(cellKey);
        return (
          <td
            key={col}
            title={failure}
            className={`${isSaving ? "saving" : ""} ${isActive ? "active-cell" : ""} ${isFillPreview ? "fill-preview" : ""} ${failure ? "save-failed" : ""}`}
            style={{ position: "relative" }}
          >
            <EditableCellInput
              value={value}
              onFocus={() => onFocusCell(col)}
              onCommit={(next) => onCommitEdit(row, col, next)}
            />
            {isActive && fillHandleEnabled && !isSaving && (
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

  const rows = Math.min(local.split("\n").length, 6);

  return (
    <textarea
      ref={ref}
      className="cell-editor"
      rows={rows}
      value={local}
      onChange={(e) => setLocal(e.target.value)}
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
