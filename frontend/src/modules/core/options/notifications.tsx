import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, ChoicesRow } from "./shared";

export function NotificationsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <ChoicesRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="rowsBeforeScroll"
        dflt={5}
        choices={[3, 5, 8]}
        setSetting={api.setSetting}
      />
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.notifications.overdueLine")}
          settings={s}
          name="overdueLine"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.notifications.unreadOnly")}
          settings={s}
          name="unreadOnly"
          dflt={false}
          setSetting={api.setSetting}
        />
      </OptionsGroup>
    </>
  );
}

/** Dealer dashboard (Wave 4 batch A): which of the dashboard's
 *  sections appear — the profile strip and the five registered
 *  sections, each with the same in-place checkbox Overview's
 *  stat tiles use. Every section defaults on (today's stack);
 *  the dashboard reads the same keys. */
