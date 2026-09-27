/**
 * Light / dark / follow-the-system.
 *
 * Three states rather than two, because "follow the system" is what most
 * people actually want and it was the only behaviour before this existed.
 * Forcing a choice would be a downgrade for anyone whose machine already
 * switches at dusk; this keeps that as the default and lets the two people
 * who want to override it do so.
 *
 * Kept apart from the button so the button file exports only a component
 * -- these are also imported by main.tsx, which applies the stored choice
 * before the first render.
 */
export type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "cobalt.theme";
export const ORDER: Theme[] = ["system", "light", "dark"];

export const THEME_LABELS: Record<Theme, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

export function storedTheme(): Theme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
  } catch {
    // Private windows and locked-down group policies can both make
    // localStorage throw rather than return null.
    return "system";
  }
}

export function rememberTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // A preference that can't be saved still applies for this session.
  }
}

/**
 * Applied to <html>, which the stylesheet keys off. "system" removes the
 * attribute entirely rather than setting it to a third value, so the
 * prefers-color-scheme rules take over on their own.
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}
