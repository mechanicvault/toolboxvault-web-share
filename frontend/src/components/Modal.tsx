import { useEffect, useRef, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";

import { useTheme } from "../theme/ThemeContext";
import { VaultFrameStack } from "./VaultPanel";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  size?: "sm" | "md" | "lg";
  /** Buttons rendered in the footer row. */
  footer?: ReactNode;
  children: ReactNode;
}

/* ------------------------------------------------------------------ */
/* Shared dialog services (deep audit F2-01 / F2-02 / F2-08): every    */
/* Modal consumer inherits a real focus trap, focus return to the     */
/* invoking control, and a background scroll lock. A module-level     */
/* stack keeps nested dialogs sane: only the topmost dialog answers   */
/* Tab/Escape, and the scroll lock is reference-counted so closing    */
/* an inner dialog never unlocks the page behind an outer one.        */
/* ------------------------------------------------------------------ */

const modalStack: object[] = [];

let scrollLockCount = 0;
let savedBodyOverflow = "";
let savedHtmlOverflow = "";

function acquireScrollLock() {
  if (scrollLockCount === 0) {
    savedBodyOverflow = document.body.style.overflow;
    savedHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
  }
  scrollLockCount += 1;
}

function releaseScrollLock() {
  scrollLockCount = Math.max(0, scrollLockCount - 1);
  if (scrollLockCount === 0) {
    document.body.style.overflow = savedBodyOverflow;
    document.documentElement.style.overflow = savedHtmlOverflow;
  }
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

function focusableDescendants(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) =>
      el.getClientRects().length > 0 &&
      getComputedStyle(el).visibility !== "hidden" &&
      !el.closest("[hidden], [inert]"),
  );
}

/**
 * The only dialog in the system. Backdrop click and Escape close it;
 * focus lands on the dialog when it opens, Tab/Shift-Tab cycle
 * inside it while it is open, background scroll is locked, and on
 * close focus returns to the control that opened it.
 *
 * Under the Steel theme the dialog wears the VaultPanel frame — the
 * same manufactured stack (well, rim runs, corners, live lamps) the
 * panels use, so a modal and a panel read as one family (owner:
 * modals onto panel geometry, 2026-10-17). The frame's CSS lives in
 * theme/vaultpanel.css; every other theme keeps the classic box.
 */
/** B-04 (Deep Audit Round 2): the control that opened the menu
 * chain an invoker lived in. When a modal is opened FROM a menu
 * item (Manage Locations, from the Inventory hamburger), the
 * menu closes in the same commit that mounts the modal, so by
 * close time the invoker is unmounted and focus would strand on
 * BODY. The chain's trigger — the hamburger button — persists,
 * so it is captured alongside the invoker: look for a
 * [aria-haspopup] control that shares a container with the menu
 * (the shell's menu pattern), or one whose aria-controls names
 * the menu. */
function menuChainTrigger(invoker: HTMLElement | null): HTMLElement | null {
  if (!invoker) return null;
  const menu = invoker.closest('[role="menu"]');
  if (!menu) return null;
  if (menu.id) {
    const byControls = document.querySelector<HTMLElement>(
      `[aria-controls="${menu.id}"]`,
    );
    if (byControls && byControls !== invoker) return byControls;
  }
  let scope: HTMLElement | null = menu.parentElement;
  for (let depth = 0; scope && depth < 4; depth += 1) {
    const trigger = Array.from(
      scope.querySelectorAll<HTMLElement>("[aria-haspopup]"),
    ).find((el) => !menu.contains(el));
    if (trigger) return trigger;
    scope = scope.parentElement;
  }
  return null;
}

export function Modal({ open, onClose, title, size = "md", footer, children }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<object>({});
  const invokerRef = useRef<HTMLElement | null>(null);
  const chainTriggerRef = useRef<HTMLElement | null>(null);
  const capturedRef = useRef(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const { theme } = useTheme();

  /* Capture the invoker DURING RENDER of the opening commit —
   * before React replaces the old tree. By effect time a menu
   * invoker is already unmounted and the browser has dropped
   * focus to BODY, which is exactly the B-04 stranding: the
   * effect-only capture read BODY and "returned" focus there.
   * BODY is never a real invoker. */
  if (open && !capturedRef.current) {
    capturedRef.current = true;
    const ae = document.activeElement;
    invokerRef.current =
      ae instanceof HTMLElement && ae !== document.body ? ae : null;
    chainTriggerRef.current = menuChainTrigger(invokerRef.current);
  }
  /* (No reset here on close: the open-effect's cleanup below
   * owns clearing the capture, and it runs AFTER this render —
   * clearing in render would wipe the invoker before the
   * cleanup can return focus to it.) */

  useEffect(() => {
    if (!open) return;
    const instance = instanceRef.current;
    modalStack.push(instance);
    /* Fallback capture for opens whose render pass happened
     * while nothing meaningful was focused (programmatic opens):
     * the render capture above wins whenever it found a control. */
    if (!invokerRef.current) {
      const ae = document.activeElement;
      invokerRef.current =
        ae instanceof HTMLElement && ae !== document.body ? ae : null;
      chainTriggerRef.current = menuChainTrigger(invokerRef.current);
    }
    acquireScrollLock();
    ref.current?.focus();

    function onKey(e: KeyboardEvent) {
      /* Only the topmost dialog answers the keyboard. */
      if (modalStack[modalStack.length - 1] !== instance) return;
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const root = ref.current;
      if (!root) return;
      const items = focusableDescendants(root);
      if (items.length === 0) {
        e.preventDefault();
        root.focus();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement as HTMLElement | null;
      if (!active || !root.contains(active)) {
        /* Focus escaped (or never entered): pull it back in. */
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
        return;
      }
      if (active === root) {
        /* The dialog container itself is focused: forward Tab
         * naturally lands on the first descendant, but Shift-Tab
         * would walk into the page behind — wrap it to the last
         * control instead. */
        if (e.shiftKey) {
          e.preventDefault();
          last.focus();
        }
        return;
      }
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    /* Capture phase: the trap must see Tab even if an inner
     * control stops propagation on keydown. */
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      const idx = modalStack.indexOf(instance);
      if (idx >= 0) modalStack.splice(idx, 1);
      releaseScrollLock();
      const invoker = invokerRef.current;
      const chainTrigger = chainTriggerRef.current;
      invokerRef.current = null;
      chainTriggerRef.current = null;
      capturedRef.current = false;
      /* Restore focus to the invoking control when it is still on
       * the page. When it is gone — the B-04 case: the invoker
       * lived in a menu that closed as the modal opened — fall
       * back to the control that opened that menu chain (the
       * hamburger trigger), never to BODY. Only when neither
       * survives do we leave focus where the close left it,
       * rather than aiming at a detached node. */
      if (invoker && invoker.isConnected) {
        invoker.focus({ preventScroll: true });
      } else if (chainTrigger && chainTrigger.isConnected) {
        chainTrigger.focus({ preventScroll: true });
      }
    };
  }, [open ]);

  if (!open) return null;

  /* Backdrop dismissal (F2-02, backdrop path): preventDefault on
   * the mousedown stops the browser's focus default — focus to
   * BODY for a non-focusable backdrop — from landing AFTER the
   * unmount-time focus return and clobbering it, which is exactly
   * what live probes showed before this guard (Esc and the ×
   * button returned focus; the backdrop did not). */
  const onBackdropMouseDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      e.preventDefault();
      onClose();
    }
  };
  const header = (
    <div className="tv-modal-header">
      <h2 className="tv-modal-title">{title}</h2>
      <button type="button" className="tv-modal-close" aria-label="Close dialog" onClick={onClose}>
        ×
      </button>
    </div>
  );
  const body = <div className="tv-modal-body">{children}</div>;
  const foot = footer ? <div className="tv-modal-footer">{footer}</div> : null;

  // Retired Steel only — Rail Steel modals take the classic
  // rendering below, with the vault treatment (corner bolts,
  // chrome close) applied by themes/railsteel.css.
  if ((theme as string) === "steel") {
    return (
      <div
        className="tv-overlay"
        onMouseDown={onBackdropMouseDown}
      >
        <div
          ref={ref}
          className={`tv-modal tv-modal--${size} tv-modal--vault tv-vault-panel`}
          role="dialog"
          aria-modal="true"
          aria-label={title}
          tabIndex={-1}
        >
          <div className="tv-vp-inner">
            <VaultFrameStack />
            <div className="tv-vp-content">
              {header}
              {body}
              {foot}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="tv-overlay"
        onMouseDown={onBackdropMouseDown}
    >
      <div
        ref={ref}
        className={`tv-modal tv-modal--${size}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        {header}
        {body}
        {foot}
      </div>
    </div>
  );
}
