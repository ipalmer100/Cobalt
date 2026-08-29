/**
 * Whether a spec is retired, read from the folder it lives in.
 *
 * Nothing inside the document says so -- the archive records it by filing
 * the spec under an "Inactive Specifications" folder, so that is what gets
 * read. Matched per path segment rather than against the whole path, so a
 * customer or file that happens to contain the word isn't swept up with
 * them.
 *
 * Shared between the sidebar and the mass-edit grid: this is a filter on
 * the whole vault, not a property of one screen, so both read it from here
 * and the app owns the on/off state.
 */
export function isInactive(root: string, path: string): boolean {
  const normRoot = root.replace(/[\\/]+$/, "");
  const rest = path.startsWith(normRoot) ? path.slice(normRoot.length) : path;
  const parts = rest.split(/[\\/]/).filter(Boolean);
  parts.pop(); // the filename is not a folder
  return parts.some((part) => /(^|[^a-z])inactive([^a-z]|$)/i.test(part));
}

export interface StatusFilter {
  showActive: boolean;
  showInactive: boolean;
}

export function passesStatus(filter: StatusFilter, root: string, path: string): boolean {
  return isInactive(root, path) ? filter.showInactive : filter.showActive;
}
