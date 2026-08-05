import { useEffect, useMemo, useState } from "react";
import { getView, writeCell, writeField } from "../api";
import type { ViewRow } from "../types";

interface Props {
  section: string;
  refreshToken: number;
  who: string;
}

const META_PREFIX = ["Spec Number", "Customer"];

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

function columnsFor(rows: ViewRow[]): string[] {
  const trailing: string[] = [];
  if (rows.some((r) => "Material Type" in r)) trailing.push("Material Type");
  trailing.push("File Path");

  const seen = new Set<string>();
  const data: string[] = [];
  for (const row of rows) {
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

export default function MassEditGrid({ section, refreshToken, who }: Props) {
  const [rows, setRows] = useState<ViewRow[]>([]);
  const [editable, setEditable] = useState(true);
  const [readonlyColumns, setReadonlyColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

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

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, refreshToken]);

  const columns = useMemo(() => columnsFor(rows), [rows]);

  async function commitEdit(rowIndex: number, column: string, value: string) {
    const row = rows[rowIndex];
    const filePath = row["File Path"] as string;
    const source = row._source;
    const key = `${filePath}:${source.section}:${source.row}:${column}`;
    setSavingKey(key);
    try {
      if (source.kind === "record") {
        const colIndex = source.header_row?.indexOf(column) ?? -1;
        if (colIndex < 0) throw new Error(`Column "${column}" not found in source table`);
        await writeCell(filePath, source.section, source.row, colIndex, value, who);
      } else {
        await writeField(filePath, source.section, column, value, who);
      }
      // Patch just this one cell instead of refetching + re-rendering the
      // whole view -- at a few thousand rows, a full reload after every
      // single edit is the actual bottleneck (seconds), not the write
      // itself (well under 200ms). We already know exactly what changed.
      setRows((prev) => {
        const next = [...prev];
        next[rowIndex] = { ...next[rowIndex], [column]: value };
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingKey(null);
    }
  }

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
      <table className="records-table editable">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => {
                const readOnly = !editable || readonlyColumns.includes(col);
                const value = (row[col] as string) ?? "";
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
                const key = `${row["File Path"]}:${row._source.section}:${row._source.row}:${col}`;
                return (
                  <td key={col} className={savingKey === key ? "saving" : ""}>
                    <input
                      defaultValue={value}
                      onBlur={(e) => {
                        if (e.target.value !== value) commitEdit(i, col, e.target.value);
                      }}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && rows.length === 0 && <div className="empty">No rows found for this view.</div>}
    </div>
  );
}
