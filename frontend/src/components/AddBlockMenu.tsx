import { useEffect, useRef, useState } from "react";

import { useT } from "../i18n/LocaleContext";

export interface AddMenuItem {
  key: string;
  title: string;
}

/**
 * The shared "+ Add" floating dropdown (Phase C, 2026-10-24):
 * one component, every seat — the Home tools row beside
 * Cancel/Save, the first shown block's chrome bar, and the
 * Overview block's stat Add all render this so the menu the user
 * opens is the same menu (same items, same dismissal: outside
 * click or Escape closes it). It lists exactly the items NOT
 * currently shown; the caller owns that list. Renders nothing
 * when there is nothing hidden to add back.
 */
export function AddBlockMenu({
  items,
  onAdd,
  className,
  menuLabel,
}: {
  items: AddMenuItem[];
  onAdd: (key: string) => void;
  className?: string;
  /** The dropdown's aria-label; defaults to Home's "Add a box".
   *  Other seats (the dealer list's Add, 2026-11-01) name their
   *  own menu without changing Home's. */
  menuLabel?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open ]);

  if (items.length === 0) return null;
  return (
    <div className={`tv-add-wrap${className ? ` ${className}` : ""}`} ref={ref}>
      <button
        type="button"
        className="tv-add-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        + {t("home.add")}
      </button>
      {open && (
        <div className="tv-add-menu" role="menu" aria-label={menuLabel ?? t("home.addBox")}>
          {items.map((b) => (
            <button
              key={b.key}
              type="button"
              role="menuitem"
              className="tv-add-item"
              onClick={() => {
                onAdd(b.key);
                setOpen(false);
              }}
            >
              {b.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
