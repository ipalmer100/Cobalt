export interface VaultEntry {
  path: string;
  supported: boolean;
  error: string | null;
  spec_number: string | null;
  customer: string | null;
  revision_number: string | null;
  warnings: string[];
}

export interface VaultResponse {
  root: string;
  entries: VaultEntry[];
}

export interface SpecSection {
  shape: "records" | "fields";
  location: string;
  header_row: string[] | null;
  rows: string[][];
  fields: Record<string, string> | null;
}

export interface SpecDetail {
  file_path: string;
  spec_number: string;
  customer: string;
  revision_number: string;
  sections: Record<string, SpecSection>;
  warnings: string[];
}

export interface ViewRowSource {
  section: string;
  kind: "record" | "field";
  row: number;
  header_row: string[] | null;
}

export interface ViewRow {
  [column: string]: unknown;
  _source: ViewRowSource;
}

export interface ViewResponse {
  section: string;
  rows: ViewRow[];
  editable: boolean;
  readonly_columns: string[];
}

export interface ViewMeta {
  editable: boolean;
  readonly_columns: string[];
}

export interface ViewsListResponse {
  views: string[];
  views_meta: Record<string, ViewMeta>;
}

export interface AuditLogEntry {
  timestamp: string;
  action: string;
  who: string;
  file_path?: string;
  spec_number?: string | null;
  section?: string;
  row?: number;
  col?: number;
  label?: string;
  old_value?: string | null;
  new_value?: string;
  values?: string[];
  revision_number?: string;
  revision_text?: string;
  source_path?: string;
  dest_path?: string;
  new_path?: string;
  customer?: string;
  [key: string]: unknown;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
}
