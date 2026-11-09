/**
 * The form two spec numbers are compared in.
 *
 * Case and surrounding whitespace are how the same number gets typed two
 * different ways, not how two specs get told apart: nobody filing `eg1001`
 * means a different document from `EG1001`. Inner runs of whitespace
 * collapse for the same reason -- a number split across a line in the
 * source table reads back with a newline in it.
 *
 * Mirrors `normalize_spec_number` in backend/cobalt/creation.py. The
 * browser's check is what disables the Create button while you type; the
 * backend's is the authority, and the two have to agree about what counts
 * as the same number or the button and the server will disagree about
 * whether a spec can be created.
 */
export function normalizeSpecNumber(value: string | null | undefined): string {
  return (value ?? "").trim().split(/\s+/).join(" ").toUpperCase();
}
