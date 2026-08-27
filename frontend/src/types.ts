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
  variant: string;
  heading: string;
  table_index: number;
}

export interface SpecDetail {
  file_path: string;
  spec_number: string;
  customer: string;
  revision_number: string;
  // A section maps to every table found for it -- normally one, but a spec
  // covering two process paths carries e.g. a Duplex and a Triplex
  // Process Routing.
  sections: Record<string, SpecSection[]>;
  warnings: string[];
  unclassified: UnclassifiedTable[];
}

export interface UnclassifiedTable {
  heading: string;
  table_index: number;
  shape: "records" | "fields";
  header_row: string[] | null;
  row_count: number;
  preview: string[][];
}

export interface ExceptionSpecRef {
  path: string;
  spec_number: string;
  table_index: number;
  row_count: number;
}

export interface ExceptionGroup {
  key: string;
  heading: string;
  shape: "records" | "fields";
  header_row: string[] | null;
  preview: string[][];
  specs: ExceptionSpecRef[];
  spec_count: number;
}

export interface ResolvedMapping {
  heading: string;
  section: string;
  who: string;
  at: string;
}

export interface ExceptionsResponse {
  pending: ExceptionGroup[];
  resolved: ResolvedMapping[];
  sections: string[];
  ignore_value: string;
}

export interface ViewRowSource {
  section: string;
  kind: "record" | "field";
  row: number;
  header_row: string[] | null;
  // Which physical table in the document this row came from. Required to
  // route a write when a spec holds several tables for one section.
  table_index: number;
  variant: string;
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
  root: string;
}

export interface BrowseEntry {
  name: string;
  path: string;
}

export interface BrowseResponse {
  path: string | null;
  parent: string | null;
  entries: BrowseEntry[];
  spec_count: number;
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
  edits?: Array<{ row: number | null; col: number | null; label: string | null; old_value: string | null; new_value: string }>;
  [key: string]: unknown;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
}

export interface BatchEditItem {
  path: string;
  section: string;
  kind: "record" | "field";
  row?: number | null;
  col?: number | null;
  label?: string | null;
  value: string;
  table_index?: number | null;
}

export interface RevisionFinding {
  path: string;
  spec_number: string;
  kind: "stated_missing" | "history_missing" | "mismatch" | "out_of_sequence" | "trailing_blank";
  detail: string;
  stated: string;
  history_last: string;
  continues_from: string;
}

export interface RevisionCheckResponse {
  checked: number;
  clean: number;
  unreadable: { path: string; error: string }[];
  findings: RevisionFinding[];
}
