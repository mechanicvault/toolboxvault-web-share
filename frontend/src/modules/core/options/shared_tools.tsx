import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function SharedToolsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow
        label={t("home.opt.shared.countsLine")}
        settings={s}
        name="showCounts"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.shared.invitesLine")}
        settings={s}
        name="showInvites"
        dflt
        setSetting={api.setSetting}
      />
    </OptionsGroup>
  );
}

/** Support (Wave 4 batch B): the open tickets ride as rows,
 *  each a link into that ticket on the Help page — 1–5 of
 *  them (3 by default, the Claims rows' shape); the rows
 *  take the place of today's single Latest line. The open
 *  count line gets its own switch. */
