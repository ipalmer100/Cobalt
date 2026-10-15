/**
 * Whether a spec is retired, read from the folder it lives in.
 *
 * Nothing inside the document says so -- the archive records it by filing
 * the spec away, so the folder is what gets read. Two words mean the same
 * thing across the division and are one category here: a spec under an
 * "Inactive Specifications" folder and one under "Obsolete" are both out
 * of use, and nobody wants to pick between two filters to say so.
 *
 * Matched per path segment rather than against the whole path, so a
 * customer or file that happens to contain the word isn't swept up. The
 * optional trailing letter catches "Obsoleted" and "Inactives" without
 * loosening the match to a bare substring, which would also catch things
 * nobody meant.
 *
 * Kept identical to _is_inactive in structure_export.py, so the survey's
 * counts and the app's filter can never disagree about which specs are
 * retired.
 *
 * Shared between the sidebar and the mass-edit grid: this is a filter on
 * the whole vault, not a property of one screen, so both read it from here
 * and the app owns the on/off state.
 */
const RETIRED_FOLDER = /(^|[^a-z])(inactive|obsolete)[sd]?([^a-z]|$)/i;

export function isInactive(root: string, path: string): boolean {
  const normRoot = root.replace(/[\\/]+$/, "");
  const rest = path.startsWith(normRoot) ? path.slice(normRoot.length) : path;
  const parts = rest.split(/[\\/]/).filter(Boolean);
  parts.pop(); // the filename is not a folder
  return parts.some((part) => RETIRED_FOLDER.test(part));
}

export interface StatusFilter {
  showActive: boolean;
  showInactive: boolean;
}

export function passesStatus(filter: StatusFilter, root: string, path: string): boolean {
  return isInactive(root, path) ? filter.showInactive : filter.showActive;
}
