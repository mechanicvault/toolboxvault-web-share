import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useT } from "../../i18n/LocaleContext";
import {
  HEADER_STATS_PER_ROW,
  HEADER_STAT_BY_KEY,
  HEADER_STAT_DEFS,
  type HeaderStatContext,
  type HeaderStatDef,
} from "./homeHeaderStats";
import "./header-stats-studio.css";

/**
 * THE HEADER STUDIO — the Home header-stats Customize popup,
 * remade from scratch (owner order, 2026-11-10 23:07) under the
 * Luxury Standard + the Through-the-User's-Eyes doctrine. The
 * v1 picker (chip strips over one long toggle list) is discarded
 * wholesale: layout, components, and CSS. What carries over is
 * only the FUNCTION and its contracts — the server reach-filtered
 * catalog (GET /api/core/header-stats), the picks + rows shape,
 * and instant save through onChange into the same `header_stats`
 * layout entry. Nothing here knows how v1 looked.
 *
 * THE DESIGN (see the lane INDEX for the full attribute map):
 * a dressing room for the header. At the top, THE STAGE: the
 * user's own header, live — the picked stats rendered with
 * their real values in the header facts register on uniform
 * studio seats inside a header plate, so what you see is
 * exactly what Home will wear. The stage's facts hold-drag
 * into a shadow that follows the pointer while the siblings
 * yield (the widget move's feel, built fresh here), and every
 * fact carries a labelled Remove pill — words, not mystery
 * icons (the doctrine: direction beats mystery; hover
 * highlights, a click presses, every change animates).
 * Below, THE COLLECTION: a category index on the left and the
 * chosen category's stats as live stat cards — each card shows
 * the stat's real current value (read through the same defs
 * the header reads) and a real button that SAYS "Add" /
 * "Remove", wearing the kit's glossy disc as its face.
 * A capacity meter counts the seats in words and segments;
 * at the cap the unpicked cards dim and the limit line says
 * why, in words, with the rows control right there to lift it.
 */

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Values for every reachable stat, read once per mount through
 *  the defs' own loads (the same reads the header itself makes,
 *  memoized through the ctx's `once`). A failed read lands in
 *  `failed` — the card shows a dash, never an invented number. */
function useStatValues(
  available: readonly string[],
  serverValues: Record<string, number>,
): { values: Record<string, string>; failed: ReadonlySet<string> } {
  const [values, setValues] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState<ReadonlySet<string>>(new Set());
  const cacheRef = useRef(new Map<string, Promise<unknown>>());
  const serverRef = useRef(serverValues);
  serverRef.current = serverValues;
  const availKey = available.join(",");

  useEffect(() => {
    let live = true;
    const ctx: HeaderStatContext = {
      serverValues: serverRef.current,
      once: (key, fn) => {
        const hit = cacheRef.current.get(key);
        if (hit) return hit as Promise<never>;
        const made = fn();
        cacheRef.current.set(key, made as Promise<unknown>);
        return made;
      },
    };
    for (const key of availKey ? availKey.split(",") : []) {
      const def = HEADER_STAT_BY_KEY.get(key);
      if (!def) continue;
      def
        .load(ctx)
        .then((value) => {
          if (live) {
            setValues((prev) =>
              prev[key] === value ? prev : { ...prev, [key]: value },
            );
          }
        })
        .catch(() => {
          if (live) {
            setFailed((prev) => {
              if (prev.has(key)) return prev;
              const next = new Set(prev);
              next.add(key);
              return next;
            });
          }
        });
    }
    return () => {
      live = false;
    };
  }, [availKey]);

  return { values, failed };
}

function reorderKeys(keys: string[], from: number, to: number): string[] {
  const next = [...keys];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

interface Gesture {
  key: string;
  pointerId: number;
  startX: number;
  startY: number;
  active: boolean;
  holdTimer: number;
  /** The pointer's total travel since the grab — the shadow's
   *  tracked offset, and the settle glide's starting point. */
  dx: number;
  dy: number;
  /** The dragged fact's seat at pickup: the shadow's birth box,
   *  and the point a cancelled drag glides home to. */
  origin: { left: number; top: number; width: number; height: number } | null;
  /** A drop/cancel glide is running; the gesture is sealed. */
  settling: boolean;
}

export function HeaderStatsStudio({
  picks,
  rows,
  available,
  serverValues,
  statLabel,
  groupLabel,
  onChange,
}: {
  picks: string[];
  rows: 1 | 2;
  available: readonly string[];
  serverValues: Record<string, number>;
  statLabel: (key: string, fallback: string) => string;
  groupLabel: (moduleId: string) => string;
  onChange: (picks: string[], rows: 1 | 2) => void;
}) {
  const t = useT();
  const max = rows * HEADER_STATS_PER_ROW;
  const availSet = useMemo(() => new Set(available), [available]);
  const pickedDefs = useMemo(
    () =>
      picks
        .map((k) => HEADER_STAT_BY_KEY.get(k))
        .filter((d): d is HeaderStatDef => !!d && availSet.has(d.key)),
    [picks, availSet],
  );
  const pickedKeys = pickedDefs.map((d) => d.key);
  const pickedSet = useMemo(() => new Set(pickedKeys), [pickedKeys]);
  const { values, failed } = useStatValues(available, serverValues);

  const groups = useMemo(() => {
    const byGroup = new Map<string, HeaderStatDef[]>();
    for (const def of HEADER_STAT_DEFS) {
      if (!availSet.has(def.key)) continue;
      const list = byGroup.get(def.module) ?? [];
      list.push(def);
      byGroup.set(def.module, list);
    }
    return [...byGroup.entries()].map(([id, defs]) => ({ id, defs }));
  }, [availSet]);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const activeGroup =
    groups.find((g) => g.id === activeGroupId) ?? groups[0];

  /* ------- order / drag state ---------------------------------- */
  const [workOrder, setWorkOrder] = useState<string[] | null>(null);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const shownKeys = workOrder ?? pickedKeys;
  const shownKeySig = shownKeys.join("|");

  const stageRef = useRef<HTMLDivElement | null>(null);
  const factRefs = useRef(new Map<string, HTMLDivElement>());
  const rectsRef = useRef(new Map<string, DOMRect>());
  const shadowRef = useRef<HTMLDivElement | null>(null);
  const gestureRef = useRef<Gesture | null>(null);
  const workOrderRef = useRef<string[] | null>(null);
  workOrderRef.current = workOrder;
  const pickedKeysRef = useRef(pickedKeys);
  pickedKeysRef.current = pickedKeys;
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  /* FLIP: whenever the shown order changes (drag retarget, add,
   * remove, rows switch), slide each fact from its last seat to
   * its new one — the widget engine's ~240ms ease, so a change
   * is a movement, never a teleport. */
  useLayoutEffect(() => {
    const reduced = prefersReducedMotion();
    factRefs.current.forEach((el, key) => {
      el.getAnimations().forEach((a) => a.cancel());
      const now = el.getBoundingClientRect();
      const prev = rectsRef.current.get(key);
      if (prev && !reduced) {
        const dx = prev.left - now.left;
        const dy = prev.top - now.top;
        if (dx !== 0 || dy !== 0) {
          el.animate(
            [
              { transform: `translate(${dx}px, ${dy}px)` },
              { transform: "none" },
            ],
            { duration: 240, easing: "cubic-bezier(0.22, 0.9, 0.3, 1)" },
          );
        }
      }
      rectsRef.current.set(key, now);
    });
  }, [shownKeySig]);

  /* ------- drag (built fresh on the widget move's model) ------- */
  const removeShadow = () => {
    shadowRef.current?.remove();
    shadowRef.current = null;
  };

  /** The gesture's teardown proper: commit a changed order (the
   *  instant save), drop the shadow, clear the drag state. Runs
   *  immediately for a plain press, and at the END of the settle
   *  glide for a real drag — the fact is never teleported home,
   *  it is carried there and set down. */
  const finishGesture = (gesture: Gesture, commitIt: boolean) => {
    if (gestureRef.current !== gesture) return;
    gestureRef.current = null;
    window.clearTimeout(gesture.holdTimer);
    if (gesture.active) {
      const order = workOrderRef.current;
      const original = pickedKeysRef.current;
      if (commitIt && order) {
        const changed =
          order.length !== original.length ||
          order.some((k, i) => k !== original[i]);
        if (changed) onChangeRef.current(order, rowsRef.current);
      }
      removeShadow();
      setWorkOrder(null);
      setDragKey(null);
    }
  };

  const endGesture = (commitIt: boolean) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.settling) return;
    window.clearTimeout(gesture.holdTimer);
    const shadow = shadowRef.current;
    if (!gesture.active || !shadow || prefersReducedMotion()) {
      finishGesture(gesture, commitIt);
      return;
    }
    /* THE SETTLE: the shadow glides the last stretch into its
     * slot — on a drop, the landing seat the siblings yielded;
     * on a cancel, the seat it was picked up from — easing from
     * its lifted scale down to rest as it arrives, and only then
     * does the real fact take the seat back. */
    gesture.settling = true;
    let tx = 0;
    let ty = 0;
    if (commitIt && gesture.origin) {
      const seatEl = factRefs.current.get(gesture.key);
      if (seatEl) {
        seatEl.getAnimations().forEach((a) => a.cancel());
        const seat = seatEl.getBoundingClientRect();
        tx =
          seat.left + seat.width / 2 - (gesture.origin.left + gesture.origin.width / 2);
        ty =
          seat.top + seat.height / 2 - (gesture.origin.top + gesture.origin.height / 2);
      }
    }
    const from = `translate(${gesture.dx}px, ${gesture.dy}px) scale(1.06)`;
    const to = `translate(${tx}px, ${ty}px) scale(1)`;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      finishGesture(gesture, commitIt);
    };
    try {
      const glide = shadow.animate(
        [{ transform: from }, { transform: to }],
        { duration: 210, easing: "cubic-bezier(0.22, 0.9, 0.3, 1)", fill: "forwards" },
      );
      glide.finished.then(finish).catch(finish);
    } catch {
      finish();
      return;
    }
    window.setTimeout(finish, 300);
  };

  const pickup = (gesture: Gesture) => {
    const el = factRefs.current.get(gesture.key);
    const stage = stageRef.current;
    if (!el || !stage) return;
    gesture.active = true;
    setDragKey(gesture.key);
    setWorkOrder([...pickedKeysRef.current]);
    /* The shadow: a clone of the fact itself, fixed at its seat,
     * that will follow the pointer 1:1 while the real fact stays
     * behind as the yielded gap. */
    removeShadow();
    const rect = el.getBoundingClientRect();
    gesture.origin = {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    };
    const clone = el.cloneNode(true) as HTMLDivElement;
    clone.classList.add("tv-hstudio-shadow");
    clone.removeAttribute("id");
    clone
      .querySelectorAll("[id]")
      .forEach((n) => n.removeAttribute("id"));
    clone
      .querySelectorAll(".tv-hstudio-fact-remove")
      .forEach((n) => n.remove());
    Object.assign(clone.style, {
      position: "fixed",
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
      margin: "0",
      zIndex: "60",
      pointerEvents: "none",
    });
    /* Born lifted: the copy arrives already scaled to its carry
     * size, and its deep shadow grows in on the fact's own
     * box-shadow transition — the lift is a movement, not a pop. */
    clone.style.transform = `translate(${gesture.dx}px, ${gesture.dy}px) scale(1.06)`;
    stage.appendChild(clone);
    shadowRef.current = clone;
  };

  /** Reading-order insertion index for a pointer position,
   *  measured against the live seats (the dragged fact's own
   *  element rides the working order as the visible gap, so
   *  every rect read here is a real seat). */
  const insertionIndex = (x: number, y: number): number => {
    const order = workOrderRef.current ?? pickedKeysRef.current;
    const key = gestureRef.current?.key;
    const others = order.filter((k) => k !== key);
    for (let i = 0; i < others.length; i++) {
      const el = factRefs.current.get(others[i]);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (y < r.top) return i;
      if (y <= r.bottom && x < r.left + r.width / 2) return i;
    }
    return others.length;
  };

  const retarget = (x: number, y: number) => {
    const gesture = gestureRef.current;
    if (!gesture?.active) return;
    const order = workOrderRef.current ?? [...pickedKeysRef.current];
    const from = order.indexOf(gesture.key);
    if (from < 0) return;
    const raw = insertionIndex(x, y);
    const without = order.filter((k) => k !== gesture.key);
    const at = Math.max(0, Math.min(raw, without.length));
    if (at === from) return;
    without.splice(at, 0, gesture.key);
    setWorkOrder(without);
  };

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const gesture = gestureRef.current;
      if (!gesture || e.pointerId !== gesture.pointerId || gesture.settling) {
        return;
      }
      const dx = e.clientX - gesture.startX;
      const dy = e.clientY - gesture.startY;
      if (!gesture.active) {
        if (Math.hypot(dx, dy) > 8) {
          window.clearTimeout(gesture.holdTimer);
          pickup(gesture);
        } else {
          return;
        }
      }
      gesture.dx = dx;
      gesture.dy = dy;
      const shadow = shadowRef.current;
      if (shadow) {
        shadow.style.transform = `translate(${dx}px, ${dy}px) scale(1.06)`;
      }
      retarget(e.clientX, e.clientY);
    };
    const onUp = (e: PointerEvent) => {
      const gesture = gestureRef.current;
      if (!gesture || e.pointerId !== gesture.pointerId || gesture.settling) {
        return;
      }
      const wasActive = gesture.active;
      endGesture(true);
      if (!wasActive) {
        /* A plain tap on a fact: give it the keyboard focus so
         * the arrow-key path is one step away (direction). */
        factRefs.current.get(gesture.key)?.focus({ preventScroll: true });
      }
    };
    const onCancel = (e: PointerEvent) => {
      const gesture = gestureRef.current;
      if (!gesture || e.pointerId !== gesture.pointerId || gesture.settling) {
        return;
      }
      endGesture(false);
    };
    const onKey = (e: KeyboardEvent) => {
      /* Escape mid-drag cancels the drag — and only the drag:
       * the dialog's own Escape (close) is left alone. Window
       * capture runs ahead of the dialog's document listener. */
      if (e.key === "Escape" && gestureRef.current?.active) {
        e.preventDefault();
        e.stopImmediatePropagation();
        endGesture(false);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      if (gestureRef.current) {
        window.clearTimeout(gestureRef.current.holdTimer);
        gestureRef.current = null;
      }
      removeShadow();
    },
    [],
  );

  const onFactPointerDown = (key: string) => (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if ((e.target as HTMLElement).closest(".tv-hstudio-fact-remove")) return;
    if (gestureRef.current) return;
    const gesture: Gesture = {
      key,
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      active: false,
      dx: 0,
      dy: 0,
      origin: null,
      settling: false,
      holdTimer: window.setTimeout(() => {
        if (gestureRef.current === gesture && !gesture.active) {
          pickup(gesture);
        }
      }, 200),
    };
    gestureRef.current = gesture;
  };

  /* ------- keyboard reorder (the pointer-free path) ------------ */
  const moveStep = (at: number, delta: number) => {
    const to = at + delta;
    if (to < 0 || to >= pickedKeys.length) return;
    onChange(reorderKeys(pickedKeys, at, to), rows);
  };
  const onFactKeyDown =
    (key: string, at: number) => (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          moveStep(at, -1);
          break;
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          moveStep(at, 1);
          break;
        case "Home":
          e.preventDefault();
          if (at > 0) onChange(reorderKeys(pickedKeys, at, 0), rows);
          break;
        case "End":
          e.preventDefault();
          if (at < pickedKeys.length - 1) {
            onChange(reorderKeys(pickedKeys, at, pickedKeys.length - 1), rows);
          }
          break;
        case "Delete":
        case "Backspace":
          e.preventDefault();
          removeStat(key);
          break;
        default:
          return;
      }
      /* Keep the keyboard seat on the moved fact. */
      requestAnimationFrame(() => {
        factRefs.current.get(key)?.focus({ preventScroll: true });
      });
    };

  /* ------- add / remove / rows --------------------------------- */
  const addStat = (key: string) => {
    if (pickedSet.has(key) || pickedKeys.length >= max) return;
    onChange([...pickedKeys, key], rows);
  };

  const removeStat = (key: string) => {
    if (!pickedSet.has(key)) return;
    const next = pickedKeys.filter((k) => k !== key);
    const el = factRefs.current.get(key);
    if (el && !prefersReducedMotion() && dragKey === null) {
      /* The fact leaves as a movement — a brief shrink-and-fade —
       * then the change commits and the siblings FLIP closed. */
      let done = false;
      const commit = () => {
        if (done) return;
        done = true;
        onChange(next, rows);
      };
      const anim = el.animate(
        [
          { opacity: 1, transform: "scale(1)" },
          { opacity: 0, transform: "scale(0.88)" },
        ],
        { duration: 150, easing: "ease-in", fill: "forwards" },
      );
      anim.finished.then(commit).catch(commit);
      window.setTimeout(commit, 220);
    } else {
      onChange(next, rows);
    }
  };

  const setRows = (next: 1 | 2) => {
    if (next === rows) return;
    /* Decided for the user (doctrine): dropping to one row keeps
     * the FIRST six — the trimmed stats simply return to the
     * collection below, unpicked, nothing lost. */
    onChange(pickedKeys.slice(0, next * HEADER_STATS_PER_ROW), next);
  };

  const atCap = pickedKeys.length >= max;
  const numericOf = (key: string): number => {
    const v = values[key];
    if (v === undefined) return Number.NaN;
    return Number.parseFloat(v.replace(/[^0-9.]/g, ""));
  };
  const alertOf = (def: HeaderStatDef): boolean => {
    const n = numericOf(def.key);
    return !!def.alertTone && Number.isFinite(n) && n > 0;
  };

  return (
    <div className="tv-hstudio">
      {/* ================= THE STAGE ================= */}
      <section className="tv-hstudio-stageblock">
        <div className="tv-hstudio-stage-head">
          <h3 className="tv-hstudio-heading">{t("home.headerStudio.stageTitle")}</h3>
          <span className="tv-hstudio-live">
            <span className="tv-hstudio-live-dot" aria-hidden="true" />
            {t("home.headerStudio.live")}
          </span>
          <div className="tv-hstudio-rows-wrap">
            <span className="tv-hstudio-rows-label" id="tv-hstudio-rows-label">
              {t("home.headerStats.rows")}
            </span>
            <div
              className="tv-hstudio-rows"
              role="group"
              aria-labelledby="tv-hstudio-rows-label"
              data-rows={rows}
            >
              <span className="tv-hstudio-rows-thumb" aria-hidden="true" />
              {([1, 2] as const).map((n) => (
                <button
                  key={n}
                  type="button"
                  className="tv-hstudio-rows-btn"
                  aria-pressed={rows === n}
                  onClick={() => setRows(n)}
                >
                  {t(n === 1 ? "home.headerStats.row1" : "home.headerStats.row2")}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div
          className="tv-hstudio-stage"
          ref={stageRef}
          data-dragactive={dragKey !== null || undefined}
        >
          {shownKeys.length === 0 ? (
            <div className="tv-hstudio-empty">
              <p className="tv-hstudio-empty-title">
                {t("home.headerStudio.emptyTitle")}
              </p>
              <p className="tv-hstudio-empty-hint">
                {t("home.headerStudio.emptyHint")}
              </p>
            </div>
          ) : (
            <div className="tv-hstudio-stage-grid" data-rows={rows}>
              {shownKeys.map((key, i) => {
                const def = HEADER_STAT_BY_KEY.get(key);
                if (!def) return null;
                const label = statLabel(def.key, def.label);
                const value = values[key];
                const aria = t("home.headerStudio.factLabel")
                  .replace("{label}", label)
                  .replace("{value}", value ?? "—")
                  .replace("{n}", String(i + 1))
                  .replace("{total}", String(shownKeys.length));
                return (
                  <div
                    key={key}
                    ref={(el) => {
                      if (el) factRefs.current.set(key, el);
                      else factRefs.current.delete(key);
                    }}
                    className="tv-hstudio-fact"
                    data-dragging={dragKey === key || undefined}
                    data-alert={alertOf(def) || undefined}
                    tabIndex={0}
                    role="button"
                    aria-label={aria}
                    onPointerDown={onFactPointerDown(key)}
                    onKeyDown={onFactKeyDown(key, i)}
                  >
                    <span className="tv-fact-label">{label}</span>
                    <span className="tv-fact-value">
                      {value !== undefined ? (
                        value
                      ) : (
                        <span className="tv-hstudio-skel" aria-hidden="true" />
                      )}
                    </span>
                    <button
                      type="button"
                      className="tv-hstudio-fact-remove"
                      aria-label={t("home.headerStudio.removeStat").replace(
                        "{label}",
                        label,
                      )}
                      onClick={() => removeStat(key)}
                    >
                      <span
                        className="tv-list-remove-btn tv-hstudio-disc"
                        aria-hidden="true"
                      >
                        −
                      </span>
                      <span>{t("home.headerStudio.remove")}</span>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="tv-hstudio-capacity">
          <div
            className="tv-hstudio-meter"
            aria-hidden="true"
            data-full={atCap || undefined}
          >
            {Array.from({ length: max }, (_, i) => (
              <span
                key={i}
                className="tv-hstudio-meter-seg"
                data-filled={i < pickedKeys.length || undefined}
              />
            ))}
          </div>
          <span className="tv-hstudio-capacity-text">
            {t("home.headerStudio.capacity")
              .replace("{count}", String(pickedKeys.length))
              .replace("{max}", String(max))}
          </span>
        </div>
        {atCap && (
          <p className="tv-hstudio-maxed" role="status">
            {t(rows > 1 ? "home.headerStudio.maxedFull" : "home.headerStats.maxed")}
          </p>
        )}
        {pickedKeys.length > 0 && (
          <p className="tv-hstudio-hint">{t("home.headerStudio.stageHint")}</p>
        )}
      </section>

      {/* ================= THE COLLECTION ================= */}
      <section className="tv-hstudio-catalog">
        <div className="tv-hstudio-catalog-head">
          <h3 className="tv-hstudio-heading">
            {t("home.headerStudio.catalogTitle")}
          </h3>
          <p className="tv-hstudio-sub">{t("home.headerStudio.catalogSub")}</p>
        </div>
        <div className="tv-hstudio-catalog-body">
          <nav className="tv-hstudio-index" aria-label={t("home.headerStudio.catalogTitle")}>
            {groups.map((g) => {
              const inHeader = g.defs.filter((d) => pickedSet.has(d.key)).length;
              const active = activeGroup?.id === g.id;
              return (
                <button
                  key={g.id}
                  type="button"
                  className="tv-hstudio-index-btn"
                  data-active={active || undefined}
                  aria-pressed={active}
                  onClick={() => setActiveGroupId(g.id)}
                >
                  <span className="tv-hstudio-index-name">{groupLabel(g.id)}</span>
                  <span className="tv-hstudio-index-count">
                    {inHeader > 0 ? (
                      <span className="tv-hstudio-index-inheader">{inHeader} · </span>
                    ) : null}
                    {g.defs.length}
                  </span>
                </button>
              );
            })}
          </nav>
          {activeGroup && (
            <div className="tv-hstudio-pane" key={activeGroup.id}>
              <div className="tv-hstudio-pane-head">
                <h4 className="tv-hstudio-pane-title">
                  {groupLabel(activeGroup.id)}
                </h4>
                <span className="tv-hstudio-pane-count">
                  {activeGroup.defs.length}
                </span>
              </div>
              <div className="tv-hstudio-cards">
                {activeGroup.defs.map((def) => {
                  const picked = pickedSet.has(def.key);
                  const label = statLabel(def.key, def.label);
                  const value = values[def.key];
                  const capped = !picked && atCap;
                  return (
                    <article
                      key={def.key}
                      className="tv-stat-card tv-hstudio-card"
                      data-picked={picked || undefined}
                      data-capped={capped || undefined}
                      data-alert={alertOf(def) || undefined}
                    >
                      {picked && (
                        <span className="tv-hstudio-card-pos" aria-hidden="true">
                          {pickedKeys.indexOf(def.key) + 1}
                        </span>
                      )}
                      <span className="tv-stat-label">{label}</span>
                      <span className="tv-stat-value">
                        {value !== undefined ? (
                          value
                        ) : failed.has(def.key) ? (
                          <span className="tv-hstudio-noval">–</span>
                        ) : (
                          <span className="tv-hstudio-skel" aria-hidden="true" />
                        )}
                      </span>
                      <button
                        type="button"
                        className="tv-hstudio-card-btn"
                        aria-pressed={picked}
                        aria-label={(picked
                          ? t("home.headerStudio.removeStat")
                          : t("home.headerStudio.addStat")
                        ).replace("{label}", label)}
                        disabled={capped}
                        onClick={() =>
                          picked ? removeStat(def.key) : addStat(def.key)
                        }
                      >
                        <span
                          className={
                            picked
                              ? "tv-list-remove-btn tv-hstudio-disc"
                              : "tv-list-add-btn tv-hstudio-disc"
                          }
                          aria-hidden="true"
                        >
                          {picked ? "−" : "+"}
                        </span>
                        <span>
                          {picked
                            ? t("home.headerStudio.remove")
                            : t("home.headerStudio.add")}
                        </span>
                      </button>
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
