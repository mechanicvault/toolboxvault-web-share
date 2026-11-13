import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { Button, Checkbox, Panel } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type {
  BlockSettingValue,
  BlockSize,
} from "../../lib/usePageLayout";
import { listSources as listFlyerSources } from "../flyers/api";
import type { FlyerSource } from "../flyers/types";
import {
  aspectsForModule,
  deriveBodySettings,
  parseCustomSettings,
  pickedBodies,
  CUSTOM_MODULE_BY_ID,
  type AspectDef,
  type AspectNumDef,
  type CustomModuleDef,
} from "./homeAspects";
import { HOME_WIDGETS, HomeWidget } from "./homeWidgets";
import { HowToVideosBlock } from "./HowToVideosBlock";
import { NotificationsBlock } from "./NotificationsBlock";
import { QuickReportsBlock } from "./QuickReportsBlock";
import { optNum } from "./widgetOptions";

/**
 * CUSTOM WIDGET RENDERING + EDITING (dashboard redesign
 * Lane 2, design §3.6). A custom box is one Panel wearing the
 * user's own name, over a stack of the module's existing
 * bodies in bare mode — each body fed the settings bundle the
 * aspect framework derives from the box's picks. The Dealer
 * Dashboard is the one whole-body exception: its sections
 * ARE the aspects, so it renders as itself with the derived
 * bundle (its own panels carry its identity, as they do in
 * its predefined box).
 */

const DealerDashboardLazy = lazy(() => import("../dealers/DealerDashboard"));

/** The seat's flyer sources, loaded once when a flyers
 *  surface needs them (the module's own source read — the
 *  same one the predefined widget's options use). */
export function useFlyerSources(enabled: boolean): FlyerSource[] | null {
  const [sources, setSources] = useState<FlyerSource[] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    listFlyerSources()
      .then((rows) => {
        if (live) setSources(rows);
      })
      .catch(() => {
        if (live) setSources([]);
      });
    return () => {
      live = false;
    };
  }, [enabled]);
  return sources;
}

export function CustomWidgetBody({
  moduleId,
  name,
  picks,
  stored,
  size,
}: {
  moduleId: string;
  name: string;
  picks: Set<string>;
  stored: Record<string, BlockSettingValue>;
  size: BlockSize;
}) {
  const t = useT();
  const mod = CUSTOM_MODULE_BY_ID[moduleId];
  const [content, setContent] = useState<Record<string, boolean>>({});
  const report = useCallback(
    (bodyId: string) => (has: boolean) =>
      setContent((prev) =>
        prev[bodyId] === has ? prev : { ...prev, [bodyId]: has },
      ),
    [],
  );
  if (!mod) return null;

  if (mod.bodies[0]?.kind === "dealerDashboard") {
    return (
      <Suspense fallback={null}>
        <DealerDashboardLazy
          settings={deriveBodySettings(mod, "main", picks, stored, null)}
        />
      </Suspense>
    );
  }

  const bodies = pickedBodies(mod, picks, null);
  // The composite owns the box's empty state: block bodies
  // describe themselves (their own empty lines render), so
  // only widget bodies report, and the box reads empty when
  // every seated body has reported and none had content.
  const widgetBodies = bodies.filter((b) => b.kind === "widget");
  const settled = widgetBodies.every((b) => content[b.id] !== undefined);
  const anyContent =
    bodies.length > widgetBodies.length ||
    widgetBodies.some((b) => content[b.id]);
  const showEmpty = bodies.length === 0 || (settled && !anyContent);

  const primary = mod.bodies[0];
  const tone =
    primary?.kind === "widget" && primary.widgetId
      ? HOME_WIDGETS[primary.widgetId]?.tone ?? "info"
      : "info";
  return (
    <Panel className="tv-home-widget">
      {/* No "Open →" button in the head (Ryan, 2026-11-10
          17:29 — retired on every Home widget); the title link
          is the door. */}
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone={tone} aria-hidden="true">
          {mod.icon}
        </span>
        <h3 className="tv-widget-title">
          <Link to={mod.door} className="tv-widget-title-link">
            {name}
          </Link>
        </h3>
      </div>
      {bodies.map((body) => {
        const bundle = deriveBodySettings(mod, body.id, picks, stored, null);
        let node: ReactNode = null;
        if (body.kind === "widget" && body.widgetId) {
          node = (
            <HomeWidget
              bare
              moduleId={body.widgetId}
              title={name}
              path={mod.door}
              size={size}
              settings={bundle}
              onContent={report(body.id)}
            />
          );
        } else if (body.kind === "videos") {
          node = <HowToVideosBlock bare editing={false} />;
        } else if (body.kind === "quickReports") {
          node = (
            <QuickReportsBlock bare editing={false} settings={bundle} />
          );
        } else if (body.kind === "notifications") {
          node = (
            <NotificationsBlock bare editing={false} settings={bundle} />
          );
        }
        return (
          <div key={body.id} className="tv-custom-part">
            {node}
          </div>
        );
      })}
      {showEmpty && <p className="tv-muted">{t("home.widgetEmpty")}</p>}
    </Panel>
  );
}

/** The aspect switch list — one row per aspect (switch +
 *  plain-language description), shared by the wizard's
 *  aspects step and the box's options panel so the two
 *  surfaces can never drift. */
export function AspectSwitchList({
  mod,
  picks,
  onToggle,
  flyerSources,
}: {
  mod: CustomModuleDef;
  picks: Set<string>;
  onToggle: (aspect: AspectDef, on: boolean) => void;
  flyerSources: FlyerSource[] | null;
}) {
  const t = useT();
  const aspects = aspectsForModule(mod, flyerSources);
  return (
    <div className="tv-aspect-list">
      {aspects.map((aspect) => (
        <div key={aspect.id} className="tv-aspect-row">
          <Checkbox
            label={aspect.labelText ?? t(aspect.labelKey)}
            checked={picks.has(aspect.id)}
            onChange={(e) => onToggle(aspect, e.target.checked)}
          />
          <p className="tv-muted tv-aspect-desc">{t(aspect.descKey)}</p>
        </div>
      ))}
      {mod.dynamicFlyers && flyerSources === null && (
        <p className="tv-muted">{t("home.wiz.loadingSources")}</p>
      )}
    </div>
  );
}

/** One segmented numeric choice (the width track's own
 *  language): the numbers this choice may take. */
export function AspectNumRow({
  numDef,
  value,
  onPick,
}: {
  numDef: AspectNumDef;
  value: number;
  onPick: (value: number) => void;
}) {
  const t = useT();
  const choices =
    numDef.choices ??
    Array.from(
      { length: numDef.max - numDef.min + 1 },
      (_, i) => numDef.min + i,
    );
  return (
    <div className="tv-block-opts-group">
      <span className="tv-block-opts-label">{t(numDef.labelKey)}</span>
      <div className="tv-opts-size" role="group" aria-label={t(numDef.labelKey)}>
        {choices.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            data-active={value === n || undefined}
            onClick={() => onPick(n)}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The numeric choices of the picked aspects, read from a
 *  settings-shaped record (a stored bundle in the panel, a
 *  draft record in the wizard). Duplicate names across
 *  aspects (Borrowing's shared visibleRows) render once. */
export function AspectNumRows({
  mod,
  picks,
  values,
  onPick,
}: {
  mod: CustomModuleDef;
  picks: Set<string>;
  values: Record<string, BlockSettingValue>;
  onPick: (numDef: AspectNumDef, value: number) => void;
}) {
  const seen = new Set<string>();
  const rows: AspectNumDef[] = [];
  for (const aspect of mod.aspects) {
    if (!picks.has(aspect.id)) continue;
    for (const n of aspect.nums ?? []) {
      if (seen.has(n.name)) continue;
      seen.add(n.name);
      rows.push(n);
    }
  }
  if (rows.length === 0) return null;
  return (
    <>
      {rows.map((n) => (
        <AspectNumRow
          key={n.name}
          numDef={n}
          value={optNum(values, n.name, n.dflt, n.min, n.max)}
          onPick={(v) => onPick(n, v)}
        />
      ))}
    </>
  );
}

/** The ⋯ options panel's content for a custom box (§3.3):
 *  its name, its aspect list (the wizard's step 2, pre-filled
 *  — re-configuring never means re-running the wizard), and
 *  the picked aspects' numbers. Every change writes through
 *  the shell's instant save, like every other box. */
export function CustomOptionsPanel({
  mod,
  settings,
  setSetting,
}: {
  mod: CustomModuleDef;
  settings: Record<string, BlockSettingValue>;
  setSetting: (name: string, value: BlockSettingValue | undefined) => void;
}) {
  const t = useT();
  const sources = useFlyerSources(Boolean(mod.dynamicFlyers));
  const parsed = parseCustomSettings(settings);
  const picks = parsed?.picks ?? new Set<string>();

  // Flyers: keep the captured source list current whenever
  // the panel opens, so a source added since the box was
  // built joins its choices (and its hidden-tracking).
  const sourcesRef = useRef<string>("");
  useEffect(() => {
    if (!mod.dynamicFlyers || !sources) return;
    const keys = sources.map((s) => s.key);
    const stamp = keys.join(",");
    if (sourcesRef.current === stamp) return;
    sourcesRef.current = stamp;
    const stored = Array.isArray(settings.csources)
      ? settings.csources.filter((x): x is string => typeof x === "string")
      : [];
    if (stored.join(",") !== stamp) {
      setSetting("csources", keys.length > 0 ? keys : undefined);
    }
  }, [mod.dynamicFlyers, sources, settings.csources, setSetting]);

  const toggle = (aspect: AspectDef, on: boolean) => {
    const next = new Set(picks);
    if (on) next.add(aspect.id);
    else next.delete(aspect.id);
    setSetting("caspects", next.size > 0 ? [...next] : undefined);
  };
  const setAll = (on: boolean) => {
    const all = aspectsForModule(mod, sources);
    setSetting(
      "caspects",
      on ? all.map((a) => a.id) : undefined,
    );
  };

  return (
    <div className="tv-custom-opts">
      <div className="tv-block-opts-group">
        <span className="tv-block-opts-label">{t("home.custom.name")}</span>
        <input
          type="text"
          className="tv-custom-name-input"
          value={typeof settings.cname === "string" ? settings.cname : ""}
          placeholder={t("home.custom.namePlaceholder")}
          maxLength={120}
          onChange={(e) =>
            setSetting(
              "cname",
              e.target.value.trim() ? e.target.value : undefined,
            )
          }
        />
      </div>
      <div className="tv-block-opts-group">
        <span className="tv-block-opts-label">{t("home.opt.whatShows")}</span>
        <div className="tv-aspect-allnone">
          <Button variant="ghost" size="sm" onClick={() => setAll(true)}>
            {t("home.wiz.all")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAll(false)}>
            {t("home.wiz.none")}
          </Button>
        </div>
        <AspectSwitchList
          mod={mod}
          picks={picks}
          onToggle={toggle}
          flyerSources={sources}
        />
      </div>
      <AspectNumRows
        mod={mod}
        picks={picks}
        values={settings}
        onPick={(n, v) => setSetting(n.name, v === n.dflt ? undefined : v)}
      />
    </div>
  );
}
