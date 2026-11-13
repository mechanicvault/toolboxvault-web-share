import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import {
  estimateMenuHeight,
  placeMenuInViewport,
} from "../lib/menuPlacement";
import { LocaleSwitcher } from "../i18n/LocaleSwitcher";
import { useT } from "../i18n/LocaleContext";
import { Link, useLocation } from "react-router-dom";
import { LinkButton } from "./Button";
import { PersonIcon } from "./icons";

export interface UserMenuUser {
  name: string;
  email: string;
  accountNumber?: string;
  /**
   * Account facts relocated from the Home side panel's account
   * box (owner, 2026-11-01): the group summary (e.g. "Mechanic /
   * Technician + Shop / Company") and the location line (public
   * area label, else country). Read-only display — the panel's
   * account number already rides the menu header above; these
   * two rows complete the box's field set in its new home.
   */
  group?: string;
  location?: string;
}

export interface UserMenuLink {
  label: string;
  path: string;
}

interface UserMenuProps {
  user: UserMenuUser | null;
  onLogout: () => void;
  /**
   * The ACCOUNT settings sections (settings restructure, owner
   * review round 1): the important account information lives under
   * the user's name — the gear menu lists these deep links into
   * the settings shell. Site settings are NOT here; they live in
   * the main menu's Settings accordion.
   */
  accountLinks?: UserMenuLink[];
  /** Operators also get their Admin door here (as before). */
  adminPath?: string | null;
  loginPath?: string;
  signupPath?: string;
}

/**
 * The account menu: identity plate + account section links +
 * log out. Its trigger is the PERSON ICON in the header cluster,
 * immediately beside the Help ? (owner, 2026-11-03 — the menu
 * used to ride the rail's top as a name block; the owner moved
 * the door here and made Home the rail's first item). The menu's
 * CONTENTS never moved — only the toggle's seat and the popup's
 * anchor. Signed out, this component renders the strip cluster
 * instead: locale switcher + log in / sign up actions (there is
 * no user menu — and no person button — signed out). Data comes
 * from the app — this component owns only the look and the
 * account menu's open/close behavior.
 */
export function UserMenu({
  user,
  onLogout,
  accountLinks = [],
  adminPath,
  loginPath = "/login",
  signupPath = "/signup",
}: UserMenuProps) {
  const t = useT();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top?: number; bottom?: number; right: number; maxHeight: number; maxWidth: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  /* Popup placement (Phase E, owner 2026-10-24 — the root fix
   * for "the account menu opens hidden behind the side panel";
   * anchor updated for the header seat, owner 2026-11-03).
   * Diagnosis, measured on the old bottom-of-rail seat: the menu
   * was absolutely positioned INSIDE the rail, and the rail clips
   * with overflow: hidden (its expanding-spine trick) inside its
   * own stacking context (sticky + z-index) — so the menu's
   * z-index could never lift it out; everything past the rail's
   * right edge was simply not painted, and the panel beside the
   * rail showed through the missing part. The fix takes the menu
   * OUT of the clipped subtree: it renders in a portal at the
   * document root with position: fixed, anchored to the trigger
   * button's live rect — below the trigger, RIGHT-aligned to it
   * (the trigger now sits in the header's top-right cluster, so
   * the menu hangs from the button's right edge like the bell
   * popup beside it). The anchor is the RIGHT edge itself, not
   * a left computed from an assumed width: the menu's width is
   * content-driven, and an assumed 300px left the real edge
   * ~48px short of the button's (measured in the relocation
   * lane's proof). Once the menu is mounted, a second pass
   * nudges the anchor if the menu's left edge would leave the
   * viewport. Vertical placement runs the shared viewport rule
   * (lib/menuPlacement, FIX 3, 2026-11-11): opens downward when
   * it fits, flips upward when the bottom runs out, otherwise
   * caps to the roomier side and scrolls inside — the old
   * `max(160, …)` floor could push the box off the bottom edge.
   * No ancestor can clip or cover it. */
  function placeMenu() {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const vw = window.innerWidth;
    let right = Math.max(8, vw - r.right);
    const menu = menuRef.current;
    if (menu) {
      // Nudge back into the viewport when right-alignment would
      // push the menu off the left edge (on phones the trigger
      // sits mid-header, so a wide menu cannot hang from its
      // right edge and stay on screen): moving the menu right
      // means DECREASING the right anchor. The layout box
      // (offsetLeft) is the measure — the entrance animation's
      // transform would skew a bounding-rect read. The maxWidth
      // cap (vw − 16) guarantees right = 0 always lands the
      // menu fully on screen, so the clamp is a hard floor.
      const menuLeft = menu.offsetLeft;
      if (menuLeft < 8) right = Math.max(0, right - (8 - menuLeft));
    }
    // The identity plate (~120px) rides over the item rows;
    // once mounted, the menu's real scrollHeight is the measure.
    const measured = menu?.scrollHeight;
    const estimated =
      measured && measured > 0
        ? measured
        : 120 +
          estimateMenuHeight(
            accountLinks.length + (adminPath ? 1 : 0) + 1,
          );
    const placed = placeMenuInViewport(r, {
      width: 300,
      estimatedHeight: estimated,
    });
    setMenuPos({
      top: placed.bottom !== undefined ? undefined : placed.top,
      bottom: placed.bottom,
      right,
      maxHeight: placed.maxHeight,
      maxWidth: Math.min(300, vw - 16),
    });
  }

  function toggle() {
    if (!open) placeMenu();
    setOpen((v) => !v);
  }

  // Route changes close the menu (the page it described is
  // gone) — the same rule the bell popup beside it runs.
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  /* Keyboard model (deep audit F2-11): the account menu now runs
   * the SAME pattern the accent gear menu beside it has always
   * had — opening moves focus onto the first item, ↑/↓ walk the
   * list with wrap, Home/End jump, and Escape closes the menu AND
   * returns focus to the trigger button (previously Escape
   * stranded focus on BODY). */
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      const inTrigger = ref.current?.contains(target);
      const inMenu = menuRef.current?.contains(target);
      if (!inTrigger && !inMenu) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    // The menu is mounted now: run the placement's second pass
    // (the left-edge nudge needs the menu's real box).
    placeMenu();
    // The menu is viewport-fixed now: keep it glued to its
    // trigger when the window resizes or any scroller moves
    // (on phones the rail strip scrolls with the page).
    window.addEventListener("resize", placeMenu);
    document.addEventListener("scroll", placeMenu, true);
    // Focus the first item so the menu is keyboard-live the
    // moment it drops.
    const items = menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]');
    if (items && items.length > 0) {
      items[0]?.focus();
    }
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", placeMenu);
      document.removeEventListener("scroll", placeMenu, true);
    };
  }, [open ]);

  function onMenuKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") {
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    if (items.length === 0) return;
    e.preventDefault();
    const idx = items.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? items.length - 1
          : e.key === "ArrowDown"
            ? (idx + 1) % items.length
            : (idx - 1 + items.length) % items.length;
    items[next]?.focus();
  }

  if (!user) {
    return (
      <span className="tv-header-actions">
        <LocaleSwitcher id="locale-switcher-header" />
        <Link to={loginPath} className="tv-header-login">
          {t("shell.login")}
        </Link>
        <LinkButton to={signupPath} size="sm">{t("shell.signup")}</LinkButton>
      </span>
    );
  }

  const menuStyle: CSSProperties | undefined = menuPos
    ? {
        // Flipped placement says top:"auto" out loud (the
        // .tv-menu base class carries its own `top`).
        top: menuPos.bottom !== undefined ? "auto" : menuPos.top,
        bottom: menuPos.bottom,
        right: menuPos.right,
        maxHeight: menuPos.maxHeight,
        maxWidth: menuPos.maxWidth,
      }
    : undefined;

  return (
    <div className="tv-usermenu-cluster">
      <div className="tv-usermenu" ref={ref}>
        <button
          ref={btnRef}
          type="button"
          className="tv-hbtn tv-usermenu-btn"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={t("shell.userMenu")}
          title={t("shell.userMenu")}
          onClick={toggle}
        >
          <PersonIcon size={19} />
        </button>
      {open && createPortal(
        <div className="tv-menu tv-menu--portal" role="menu" ref={menuRef} onKeyDown={onMenuKey} style={menuStyle}>
          <div className="tv-menu-header">
            {/* The account facts ride in the dark outlined plate
              * the retired side panel's account box wore (owner,
              * 2026-11-01: "in a dark box as an outline just like
              * before. I liked that") — .tv-menu-acctbox in
              * surfaces.css mirrors .tv-sp-acct's treatment. */}
            <div className="tv-menu-acctbox">
              <div className="tv-menu-user-name" style={{ fontWeight: 700 }}>{user.name}</div>
              <div className="tv-menu-user-email" style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>
                {user.email}
              </div>
              {user.accountNumber && (
                <div
                  style={{
                    color: "var(--accent)",
                    fontSize: "var(--font-size-sm)",
                    fontWeight: 700,
                    letterSpacing: "0.04em",
                  }}
                >
                  {user.accountNumber}
                </div>
              )}
              {(user.group || user.location) && (
                <dl className="tv-menu-acct">
                  {user.group && (
                    <div>
                      <dt>{t("home.panel.group")}</dt>
                      <dd>{user.group}</dd>
                    </div>
                  )}
                  {user.location && (
                    <div>
                      <dt>{t("home.panel.location")}</dt>
                      <dd>{user.location}</dd>
                    </div>
                  )}
                </dl>
              )}
            </div>
          </div>
          {accountLinks.map((link) => (
            <Link
              key={link.path}
              to={link.path}
              className="tv-menu-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          {adminPath && (
            <Link
              to={adminPath}
              className="tv-menu-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              Admin
            </Link>
          )}
          <button
            type="button"
            className="tv-menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
          >
            {t("shell.logout")}
          </button>
        </div>,
        document.body,
      )}
      </div>
    </div>
  );
}
