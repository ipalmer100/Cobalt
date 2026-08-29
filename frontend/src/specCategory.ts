import type { SpecCategory } from "./types";

/**
 * Spec categories, and what each one is offered.
 *
 * Not every spec in the archive is the same kind of document. The blown
 * film specs are built around sections no other spec has and are far
 * enough from the standard shape that editing them in the same grid was
 * wrong: one fill, one revision, one set of columns spanning documents
 * that do not resemble each other.
 *
 * So Mass Edit is the standard category, and every other category is read
 * and edited a spec at a time in Spec Detail. Nothing is hidden and
 * nothing is read-only -- a blown film spec is fully editable, just on its
 * own terms.
 *
 * The order here is the order the filter shows them in.
 */
export const CATEGORY_LABELS: Record<SpecCategory, string> = {
  standard: "Standard",
  "blown-film": "Blown Film",
};

/** Categories that Mass Edit covers. */
export const MASS_EDITABLE: SpecCategory[] = ["standard"];

export function isMassEditable(category: SpecCategory | null | undefined): boolean {
  return !!category && MASS_EDITABLE.includes(category);
}

/** The sidebar filter: one category, or all of them. */
export type CategoryFilter = SpecCategory | "all";

export function categoryLabel(category: SpecCategory | null | undefined): string {
  return category ? CATEGORY_LABELS[category] ?? category : "";
}
