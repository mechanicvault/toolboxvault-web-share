import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type {
  BlockSettingValue,
  BlockSize,
  StoredBlockEntry,
} from "../../lib/usePageLayout";
import {
  defaultPicks,
  newCustomKey,
  CUSTOM_MODULE_BY_ID,
  type CustomModuleDef,
} from "./homeAspects";
import {
  AspectNumRows,
  AspectSwitchList,
  CustomWidgetBody,
  useFlyerSources,
} from "./CustomWidgetBody";

/**
 * THE CUSTOM-WIDGET WIZARD (dashboard redesign Lane 2,
 * design §3.6; TWO steps since the widget uniformity lane,
 * 2026-11-10, owner order — the old steps 2 and 3 merged):
 * pick a module → build the box on ONE page: name, width and
 * numbers with the LIVE PREVIEW (the user's real data) at the
 * TOP of the page, the aspects list below it — toggling an
 * aspect updates the preview on the same page. Nothing is
 * saved until Add; Back/Cancel abandon the draft cleanly.
 * The defaults ARE the module's predefined recipe, so a box
 * at defaults is two taps: module, Add.
 *
 * Editing an existing custom does NOT re-enter this wizard —
 * by Lane 2's settled design it never did: ⋯ → Edit options
 * opens the in-place CustomOptionsPanel (name + the same
 * aspect list pre-filled + numbers) on the box itself, and
 * ⋯ → Rename… renames it. The two-step merge changes nothing
 * about that flow.
 */

export interface WizardModuleOffer {
  mod: CustomModuleDef;
  /** The host entry's localized title — the module's name
   *  for this seat, and the box's default name. */
  title: string;
  defaultSize: BlockSize;
}

export function HomeWizard({
  offered,
  onCancel,
  onAdd,
}: {
  offered: WizardModuleOffer[];
  onCancel: () => void;
  onAdd: (block: StoredBlockEntry) => void;
}) {
  const t = useT();
  const [step, setStep] = useState<1 | 2>(1);
  const [moduleId, setModuleId] = useState<string | null>(null);
  const [picks, setPicks] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [size, setSize] = useState<BlockSize>("full");
  const [nums, setNums] = useState<Record<string, number>>({});

  const offer = offered.find((o) => o.mod.id === moduleId) ?? null;
  const mod = offer ? CUSTOM_MODULE_BY_ID[offer.mod.id] : null;
  const sources = useFlyerSources(Boolean(mod?.dynamicFlyers));

  // Flyers: source aspects join the recipe when the source
  // list lands (it usually beats the user's first tap).
  const mergedSources = useRef<string>("");
  useEffect(() => {
    if (!mod?.dynamicFlyers || !sources) return;
    const stamp = sources.map((s) => s.key).join(",");
    if (mergedSources.current === stamp) return;
    mergedSources.current = stamp;
    setPicks((prev) => {
      const next = new Set(prev);
      for (const s of sources) next.add(`src:${s.key}`);
      return next;
    });
  }, [mod, sources]);

  const pickModule = (o: WizardModuleOffer) => {
    setModuleId(o.mod.id);
    setPicks(defaultPicks(o.mod, null));
    setName(o.title);
    setSize(o.defaultSize);
    setNums({});
    mergedSources.current = "";
    setStep(2);
  };

  const draftSettings = useMemo<Record<string, BlockSettingValue>>(() => {
    if (!mod) return {};
    const out: Record<string, BlockSettingValue> = {
      cmodule: mod.id,
      caspects: [...picks],
    };
    const trimmed = name.trim();
    if (trimmed && offer && trimmed !== offer.title) out.cname = trimmed;
    for (const [k, v] of Object.entries(nums)) out[k] = v;
    if (mod.dynamicFlyers && sources) {
      out.csources = sources.map((s) => s.key);
    }
    return out;
  }, [mod, picks, name, nums, sources, offer]);

  const add = () => {
    if (!mod || picks.size === 0) return;
    onAdd({
      key: newCustomKey(),
      visible: true,
      size,
      settings: draftSettings,
    });
  };

  return (
    <div className="tv-wizard">
      <div className="tv-wiz-head">
        <strong>{offer?.title ?? t("home.wiz.title")}</strong>
        <span className="tv-muted">
          {t("home.wiz.step")
            .replace("{n}", String(step))
            .replace("{total}", "2")}
        </span>
      </div>

      {step === 1 && (
        <>
          <p className="tv-muted">{t("home.wiz.pickModule")}</p>
          <div className="tv-wiz-modules">
            {offered.map((o) => (
              <button
                key={o.mod.id}
                type="button"
                className="tv-wiz-module"
                onClick={() => pickModule(o)}
              >
                <span className="tv-stat-icon" data-tone="info" aria-hidden="true">
                  {o.mod.icon}
                </span>
                <span>{o.title}</span>
              </button>
            ))}
          </div>
          <div className="tv-wiz-foot">
            <Button variant="ghost" onClick={onCancel}>
              {t("home.wiz.cancel")}
            </Button>
          </div>
        </>
      )}

      {step === 2 && mod && offer && (
        <>
          {/* The old step 3, at the TOP of the merged page
           * (owner order, 2026-11-10): name, width, numbers,
           * the live preview, and Add — then the aspects
           * below, updating that same preview. */}
          <div className="tv-block-opts-group">
            <span className="tv-block-opts-label">
              {t("home.wiz.name")}
            </span>
            <input
              type="text"
              className="tv-custom-name-input"
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="tv-block-opts-group">
            <span className="tv-block-opts-label">
              {t("home.boxWidth")}
            </span>
            <div
              className="tv-opts-size"
              role="group"
              aria-label={t("home.boxWidth")}
            >
              {(["half", "full"] as BlockSize[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={size === s}
                  data-active={size === s || undefined}
                  onClick={() => setSize(s)}
                >
                  {t(s === "half" ? "home.widthHalf" : "home.widthFull")}
                </button>
              ))}
            </div>
          </div>
          <AspectNumRows
            mod={mod}
            picks={picks}
            values={nums}
            onPick={(n, v) =>
              setNums((prev) => ({ ...prev, [n.name]: v }))
            }
          />

          <div className="tv-wiz-preview">
            <span className="tv-block-opts-label">
              {t("home.wiz.preview")}
            </span>
            <div className="tv-wiz-preview-box" data-size={size}>
              <CustomWidgetBody
                moduleId={mod.id}
                name={name.trim() || offer.title}
                picks={picks}
                stored={draftSettings}
                size={size}
              />
            </div>
          </div>

          <div className="tv-wiz-rowhead">
            <p className="tv-muted">{t("home.wiz.pickAspects")}</p>
            <div className="tv-aspect-allnone">
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setPicks(
                    new Set(
                      [
                        ...mod.aspects.map((a) => a.id),
                        ...(sources ?? []).map((s) => `src:${s.key}`),
                      ],
                    ),
                  )
                }
              >
                {t("home.wiz.all")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPicks(new Set())}
              >
                {t("home.wiz.none")}
              </Button>
            </div>
          </div>
          <AspectSwitchList
            mod={mod}
            picks={picks}
            flyerSources={sources}
            onToggle={(aspect, on) =>
              setPicks((prev) => {
                const next = new Set(prev);
                if (on) next.add(aspect.id);
                else next.delete(aspect.id);
                return next;
              })
            }
          />
          {picks.size === 0 && (
            <p className="tv-muted">{t("home.wiz.needAspect")}</p>
          )}

          {/* Sweep B1 (01-F14): the commitment sits AFTER the
           * choices it commits — Back / Add to my Home in a
           * sticky footer, like the Studio's DONE, so a user who
           * scrolled the aspects never scrolls back up to finish. */}
          <div className="tv-wiz-foot tv-wiz-foot--commit">
            <Button variant="ghost" onClick={() => setStep(1)}>
              {t("home.wiz.back")}
            </Button>
            <Button disabled={picks.size === 0} onClick={add}>
              {t("home.wiz.add")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
