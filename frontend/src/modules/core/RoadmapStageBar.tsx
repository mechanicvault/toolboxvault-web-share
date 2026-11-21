import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import "./roadmap.css";

/**
 * The roadmap's 8 stages (owner's pipeline, 2026-11-12), in
 * order. The backend validates the same vocabulary
 * (core/roadmap.py STAGES); the labels are the owner's words,
 * carried by the dictionaries.
 */
export const ROADMAP_STAGES = [
  "idea",
  "approved_idea",
  "awaiting_schedule",
  "scheduled",
  "building_started",
  "building_finished",
  "testing",
  "released",
] as const;

export type RoadmapStage = (typeof ROADMAP_STAGES)[number];

export function stageLabelKey(stage: string): DictKey {
  return `roadmap.stage.${stage}` as DictKey;
}

/**
 * The stepped status bar: one segment per stage, filled with
 * the accent up to and including the current stage. Desktop
 * shows the stage names along the bar; on a narrow screen the
 * names give way to the current stage in words (roadmap.css).
 * `labels={false}` drops the name row (the admin list, where
 * the stage dropdown already names it).
 */
export function RoadmapStageBar({
  stage,
  labels = true,
}: {
  stage: string;
  labels?: boolean;
}) {
  const t = useT();
  const found = ROADMAP_STAGES.indexOf(stage as RoadmapStage);
  const idx = found >= 0 ? found : 0;
  const current = t(stageLabelKey(ROADMAP_STAGES[idx]));
  return (
    <div
      className="tv-rmbar"
      role="img"
      aria-label={`${t("roadmap.stageOf").replace("{n}", String(idx + 1))}: ${current}`}
    >
      <div className="tv-rmbar-track" aria-hidden="true">
        {ROADMAP_STAGES.map((s, i) => (
          <span
            key={s}
            className={`tv-rmbar-seg${i <= idx ? " is-done" : ""}${i === idx ? " is-now" : ""}`}
          />
        ))}
      </div>
      {labels && (
        <div className="tv-rmbar-labels" aria-hidden="true">
          {ROADMAP_STAGES.map((s, i) => (
            <span
              key={s}
              className={
                i === idx ? "is-now" : i < idx ? "is-done" : undefined
              }
            >
              {t(stageLabelKey(s))}
            </span>
          ))}
        </div>
      )}
      <p className="tv-rmbar-now">
        {t("roadmap.stageWord")}: <strong>{current}</strong>
      </p>
    </div>
  );
}
