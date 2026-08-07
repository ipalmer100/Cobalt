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

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

function rowKey(row: ViewRow): string {
  return `${row["File Path"]}|${row._source.section}|${row._source.row}`;
}

function cellText(row: ViewRow, column: string): string {
  return (row[column] as string) ?? "";
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

// Only the first few rows are examined -- every row in a given section shares
// the same header_row/field keys, so scanning all of them on every render
// (which would happen on every single edit, since editing creates a new
// `rows` array) is wasted work at thousands of rows.
function columnsFor(rows: ViewRow[]): string[] {
  const trailing: string[] = [];
  if (rows.some((r) => "Material Type" in r)) trailing.push("Material Type");
  trailing.push("File Path");

  const seen = new Set<string>();
  const data: string[] = [];
  for (const row of rows.slice(0, 5)) {
    const headerRow = row._source.header_row;
    const keys = headerRow ?? Object.keys(row).filter((k) => k !== "_source");
    for (const key of keys) {
      if (META_PREFIX.includes(key) || trailing.includes(key) || key === "_source") continue;
      if (!seen.has(key)) {
        seen.add(key);
        data.push(key);
      }
    }
  }
  return [...META_PREFIX, ...data, ...trailing];
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingKeys, setSavingKeys] = useState<Set<string>>(new Set());

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

  const columns = useMemo(() => columnsFor(rows), [rows]);

  const filteredRows = useMemo(() => {
    const active = Object.entries(filters);
    if (active.length === 0) return rows;
    return rows.filter((row) => active.every(([col, allowed]) => allowed.has(cellText(row, col))));
  }, [rows, filters]);

  const sortedRows = useMemo(() => {
    if (!sortColumn) return filteredRows;
    const sorted = [...filteredRows].sort((a, b) => {
      const cmp = compareValues(cellText(a, sortColumn), cellText(b, sortColumn));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [filteredRows, sortColumn, sortDir]);

  const flatRowIndexByKey = useMemo(() => {
    const map = new Map<string, number>();
    sortedRows.forEach((row, i) => map.set(rowKey(row), i));
    return map;
  }, [sortedRows]);

  const displayItems = useMemo<DisplayItem[]>(() => {
    if (!groupByColumn) return sortedRows.map((row) => ({ type: "row", row }));
    const groups = new Map<string, ViewRow[]>();
    for (const row of sortedRows) {
      const key = cellText(row, groupByColumn);
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
  }, [sortedRows, groupByColumn, collapsedGroups]);

  const distinctValuesForOpenColumn = useMemo(() => {
    if (!openFilterColumn) return [];
    const set = new Set(rows.map((r) => cellText(r, openFilterColumn)));
    return Array.from(set).sort((a, b) => compareValues(a, b));
  }, [rows, openFilterColumn]);

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

  async function commitEdit(row: ViewRow, column: string, value: string) {
    const key = rowKey(row);
    const cellKey = `${key}:${column}`;
    const source = row._source;
    setSavingKeys((prev) => new Set(prev).add(cellKey));
    try {
      if (source.kind === "record") {
        const colIndex = source.header_row?.indexOf(column) ?? -1;
        if (colIndex < 0) throw new Error(`Column "${column}" not found in source table`);
        await writeCell(row["File Path"] as string, source.section, source.row, colIndex, value, who);
      } else {
        await writeField(row["File Path"] as string, source.section, column, value, who);
      }
      patchRows(new Map([[key, { [column]: value }]]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
      if (source.kind === "record") {
        const colIndex = source.header_row?.indexOf(drag.column) ?? -1;
        if (colIndex < 0) continue;
        edits.push({ path, section: source.section, kind: "record", row: source.row, col: colIndex, value: drag.sourceValue });
      } else {
        edits.push({ path, section: source.section, kind: "field", label: drag.column, value: drag.sourceValue });
      }
      patches.set(rowKey(row), { [drag.column]: drag.sourceValue });
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
                  editable={editable}
                  readonlyColumns={readonlyColumns}
                  activeCell={activeCell}
                  dragging={dragging}
                  fillHandleEnabled={fillHandleEnabled}
                  savingKeys={savingKeys}
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
  row: ViewRow;
  columns: string[];
  editable: boolean;
  readonlyColumns: string[];
  activeCell: { key: string; column: string } | null;
  dragging: DragState | null;
  fillHandleEnabled: boolean;
  savingKeys: Set<string>;
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
  editable,
  readonlyColumns,
  activeCell,
  dragging,
  fillHandleEnabled,
  savingKeys,
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
        const value = cellText(row, col);
        if (col === "File Path") {
          return (
            <td key={col} title={value}>
              {fileName(value)}
            </td>
          );
        }
        if (readOnly) {
          return <td key={col}>{value}</td>;
        }
        const cellKey = `${key}:${col}`;
        const isActive = activeCell?.key === key && activeCell.column === col;
        const isDragSource = dragging?.sourceKey === key && dragging.column === col;
        const isFillPreview = dragging != null && dragging.column === col && rowInDragRange && !isDragSource;
        const isSaving = savingKeys.has(cellKey);
        return (
          <td
            key={col}
            className={`${isSaving ? "saving" : ""} ${isActive ? "active-cell" : ""} ${isFillPreview ? "fill-preview" : ""}`}
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
function EditableCellInput({ value, onFocus, onCommit }: EditableCellInputProps) {
  const [local, setLocal] = useState(value);

  useEffect(() => {
    setLocal(value);
  }, [value]);

  return (
    <input
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      onFocus={onFocus}
      onBlur={() => {
        if (local !== value) onCommit(local);
      }}
    />
  );
}
