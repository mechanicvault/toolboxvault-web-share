import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
} from "react";

import { Button } from "./Button";

/**
 * THE FLOATING SAVE (dashboard-flare lane, owner order
 * 2026-11-09 — Ryan's example: organizing dashboard widgets,
 * then scrolling back to the top just to save). One reusable
 * pattern for every edit surface taller than the screen:
 *
 * The save keeps its normal seat in the form. An
 * IntersectionObserver watches that seat; the moment it
 * scrolls out of view, a floating twin — same label, same
 * props, same action — pins to the bottom-right of the
 * screen, above the content, in both themes, on phone and
 * desktop alike. When everything fits (or the user scrolls
 * back), the twin is gone and only the seated save remains.
 *
 * The twin is a second render of the SAME Button with the
 * SAME props inside the same form, so a click on either is
 * the one save — a submit stays a submit, a disabled or
 * busy save disables both, and there is no second handler
 * to drift or double-fire. Surfaces whose save already
 * lives in a fixed footer (modals, wizards) do not use
 * this — their save never leaves the screen.
 */
export function StickySaveButton(props: ComponentProps<typeof Button>) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [offscreen, setOffscreen] = useState(false);

  useEffect(() => {
    const el = anchorRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => setOffscreen(!entries[0].isIntersecting),
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <>
      <span ref={anchorRef} className="tv-sticky-save-anchor">
        <Button {...props} />
      </span>
      {offscreen && (
        <span className="tv-sticky-save">
          <Button {...props} />
        </span>
      )}
    </>
  );
}
