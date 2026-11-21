import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { useNotifications } from "../NotificationTicker";

/**
 * The panel utility block (Rail Steel conversion, Phase 1):
 *  - the global search well — submits to the global results page
 *    (/search?q=…), the same destination the header cluster's
 *    search carries (global search, owner spec 2026-10-25), and
 *  - the notifications line: the ticker's data flow
 *    (useNotifications, GET /core/notifications) rendered as a
 *    panel note line showing its newest item. Empty = renders
 *    nothing, exactly like the ticker.
 * Composition (registry header): the search sits directly under
 * the panel's title block where a panel carries it; the note line
 * follows the search.
 */
export function PanelUtility({ search = true }: { search?: boolean }) {
  const t = useT();
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const items = useNotifications(true, 20);
  const note = items[0];
  return (
    <>
      {search && (
        <form
          role="search"
          className="tv-sp-search"
          onSubmit={(e) => {
            e.preventDefault();
            const q = value.trim();
            navigate(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
          }}
        >
          <input
            type="search"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t("shell.searchPlaceholder")}
            aria-label={t("shell.searchPlaceholder")}
            className="tv-input"
          />
        </form>
      )}
      {note && (
        <div className="tv-sp-note tv-sp-note--latest">
          <p className="tv-sp-note-title">{t("home.latest")}</p>
          <p>{note.text}</p>
        </div>
      )}
    </>
  );
}
