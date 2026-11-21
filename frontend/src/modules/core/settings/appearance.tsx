import { Button, Panel } from "../../../components";
import { AccentSwatches } from "../../../theme/AccentDots";
import { useTheme } from "../../../theme/ThemeContext";
import { ThemeModePlate, ThemeSwitcher } from "../../../theme/ThemeSwitcher";
import { LocaleSwitcher } from "../../../i18n/LocaleSwitcher";
import { useLocale, useT } from "../../../i18n/LocaleContext";

export function AppearanceSection() {
  const t = useT();
  const { locale } = useLocale();
  const { mode } = useTheme();
  return (
    <Panel title={t("settings.appearance.title")} variant="plate">
      {/* F1-28: the section composes like its siblings — controls
          on the left, a LIVE preview on the right (it re-renders
          in the current theme/accent because it uses the same
          tokens), instead of one short panel in a sea of grey. */}
      <div
        style={{
          display: "grid",
          gap: "var(--space-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
        }}
      >
      <div style={{ display: "grid", gap: "var(--space-4)", alignContent: "start" }}>
        <div>
          <p className="tv-settings-block-label">
            {t("settings.appearance.theme")}
          </p>
          {/* Rail Steel Phase 3: ThemeSwitcher is the whole theme
              control — a single current-design plate. There is NO
              Layout picker and NO Header-variant picker here:
              both contexts are pinned and the rail shell ignores
              them, so offering them would be a silent lie. The
              providers stay mounted for their importers. */}
          <ThemeSwitcher />
        </div>
        <div>
          <p className="tv-settings-block-label">
            {t("settings.appearance.mode")}
          </p>
          {/* Light-mode seam (owner steer, 2026-10-24): the mode
              row sits beside the design plate from today, bound
              to ThemeContext's mode. When the light palette
              lands, this plate becomes the Light/Dark toggle —
              no section restructuring. It is a plate, not a
              switch, until there is a second palette to switch
              to. */}
          <ThemeModePlate
            label={t(
              mode === "dark"
                ? "settings.appearance.modeDark"
                : "settings.appearance.modeLight",
            )}
          />
        </div>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.appearance.accent")}
          </p>
          <AccentSwatches />
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }}>
{t("settings.appearance.accentHelper")}
          </p>
        </div>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.appearance.language")}
          </p>
          <LocaleSwitcher id="locale-switcher-settings" />
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }}>
            {t("settings.appearance.languageBody")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }} lang={locale}>
            {t("settings.appearance.translationNote")}
          </p>
        </div>
      </div>
      <div aria-hidden="true" style={{ alignContent: "start", display: "grid", gap: "var(--space-3)" }}>
        <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.appearance.previewTitle")}</p>
        <Panel title={t("settings.appearance.previewPanelTitle")}>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <span style={{ fontSize: "var(--font-size-2xl)", fontWeight: 800 }}>$19,004</span>
            <span style={{ color: "var(--text-muted)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
              {t("settings.appearance.previewReplacementCost")}
            </span>
            <div>
              <Button size="sm">{t("settings.appearance.previewPrimaryButton")}</Button>
            </div>
          </div>
        </Panel>
      </div>
      </div>
    </Panel>
  );
}

/* ----------------------------- Notifications -------------------------- */

