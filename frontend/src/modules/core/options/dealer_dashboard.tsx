import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function DealerDashboardOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const rows: { name: string; label: string }[] = [
    { name: "showProfile", label: t("home.opt.dealer.profile") },
    { name: "showWarrantyRequests", label: t("home.opt.dealer.warrantyRequests") },
    { name: "showWarrantyClaims", label: t("home.opt.dealer.warrantyClaims") },
    { name: "showRoute", label: t("home.opt.dealer.route") },
  ];
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      {rows.map((row) => (
        <CheckRow
          key={row.name}
          label={row.label}
          settings={s}
          name={row.name}
          dflt
          setSetting={api.setSetting}
        />
      ))}
    </OptionsGroup>
  );
}

/** Maintenance (Wave 4 batch A): the two count lines are
 *  individually hideable (both on = today's combined line), the
 *  coming-up list can step aside for today's single Next line,
 *  and its rows show 1–5 before scrolling.
 *
 *  Claims merge (2026-11-06): the retired Claims widget's
 *  choices live here now — the open-claims line, the
 *  backordered line, the recent-claims list with its row
 *  count, and the Repair claims / history buttons. Every one
 *  defaults ON, the union of what the two widgets showed. */
