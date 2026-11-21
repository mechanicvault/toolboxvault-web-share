import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function MessagingOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow
        label={t("home.opt.messaging.unreadLine")}
        settings={s}
        name="showUnread"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.messaging.requestsLine")}
        settings={s}
        name="showRequests"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.messaging.conversations")}
        settings={s}
        name="showConversations"
        dflt
        setSetting={api.setSetting}
      />
    </OptionsGroup>
  );
}

/** Wishlist (Wave 4 batch B, parked): the three lines each
 *  get a switch (all on = today), and the wanted items ride
 *  as rows — how many show before the rest scroll; 0 puts
 *  the rows away and today's Latest line returns. */
