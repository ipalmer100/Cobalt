import { useEffect, useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "rows"> & {
  value: string;
  textareaRef?: (el: HTMLTextAreaElement | null) => void;
};

/**
 * A textarea that is exactly as tall as the text inside it.
 *
 * Cell editors used to take `rows={value.split("\n").length}`, which counts
 * hard line breaks and nothing else. Most real spec values have none: a BOM
 * "Raw Material" naming both sides of a film is one long line that wraps to
 * three when the column is narrow. Read-only, you saw three lines; pressing
 * Edit swapped in a one-row box and the value all but disappeared -- the
 * reported "data can barely be seen once edit mode is enabled".
 *
 * Measuring the wrapped text is the only reliable way to match: how many
 * lines a value takes depends on the column's width, the font and where the
 * words break, none of which is knowable from the string. So the height is
 * set from scrollHeight after layout, and re-measured whenever the value or
 * the column width changes.
 */
export default function AutoTextarea({ value, textareaRef, ...rest }: Props) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const lastWidth = useRef(0);

  function resize(el: HTMLTextAreaElement) {
    // Collapse first: scrollHeight can only report content taller than the
    // box, so measuring without this never shrinks a cell back down.
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  useLayoutEffect(() => {
    if (ref.current) resize(ref.current);
  }, [value]);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Column widths shift as the window resizes or a filter changes what is
    // in the column, and the same text then wraps to a different number of
    // lines. Width only -- reacting to the height we just set ourselves
    // would loop.
    const observer = new ResizeObserver(() => {
      const width = el.clientWidth;
      if (width === lastWidth.current) return;
      lastWidth.current = width;
      resize(el);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <textarea
      {...rest}
      value={value}
      rows={1}
      ref={(el) => {
        ref.current = el;
        textareaRef?.(el);
      }}
    />
  );
}
