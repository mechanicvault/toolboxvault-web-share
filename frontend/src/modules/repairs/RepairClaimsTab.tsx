import { useEffect, useState, type ReactNode } from "react";
import { Panel, Spinner } from "../../components";
import { api } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { SideList, SideListRow } from "../../components/SideList";
import { BrokenItemActions } from "../claims/BrokenItemActions";
import { ClaimsList, isHistoryClaim } from "../claims/ClaimsList";
import { claimsApi, listClaims } from "../claims/api";
import type { AssetSearchItem } from "../inventory/types";
import "./repairs.css";

/**
 * Repair Claims as an Inventory tab (owner, sheet row 136,
 * 2026-11-18): the whole repair-claims half of the retired
 * Repairs & Maintenance page, in the Side List layout the
 * owner named for it — New Repair / Open Repairs / History
 * Repairs down the left, the picked section's body on the
 * right. Open and History are the settled claims lists
 * (ClaimsList, itself the R2 Side List) exactly as the old
 * page carried them.
 *
 * New Repair: a warranty claim is born from its item (the
 * claims doctrine — there is no free-standing filing
 * wizard), so the section picks the item first, then runs
 * that item's own repair panel (BrokenItemActions — the
 * same panel the item page carries: start a claim, replace,
 * or retire) in place.
 *
 * The section state is CONTROLLED from the list page (the
 * row 134 pattern): the tab strip unmounts inactive tab
 * content, so the place lives one level up.
 */

export type RepairSectionId = "new" | "open" | "history";

function NewRepairPanel() {
  const t = useT();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<AssetSearchItem[] | null>(null);
  const [picked, setPicked] = useState<AssetSearchItem | null>(null);

  // The pick list is the owner's own items, loaded once and
  // filtered as they type — a picker wants the whole shelf
  // in hand, not a search round-trip per keystroke. The
  // read caps at the endpoint's 200 limit.
  useEffect(() => {
    let cancelled = false;
    api<AssetSearchItem[]>(`/inventory/search/all?limit=200`)
      .then((rows) => {
        if (!cancelled) setItems(rows);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const needle = query.trim().toLowerCase();
  const hits =
    items === null
      ? null
      : items
          .filter((item) => !needle || item.name.toLowerCase().includes(needle))
          .slice(0, 25);

  return (
    <div className="tv-stack">
      <div className="tv-repair-pick">
        <input
          type="search"
          className="tv-input tv-repair-pick-input"
          placeholder={t("inventory.repair.searchPlaceholder")}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPicked(null);
          }}
          aria-label={t("inventory.repair.searchPlaceholder")}
        />
        {hits === null ? (
          <Spinner label="Loading…" />
        ) : (
          <div className="tv-repair-pick-list" role="listbox">
            {hits.length === 0 && (
              <p className="tv-repair-pick-empty">
                {t("inventory.repair.noMatches")}
              </p>
            )}
            {hits.map((hit) => (
              <button
                key={`${hit.item_kind}-${hit.id}`}
                type="button"
                className="tv-repair-pick-row"
                aria-selected={picked?.id === hit.id}
                onClick={() => setPicked(hit)}
              >
                {hit.name}
              </button>
            ))}
          </div>
        )}
      </div>
      {picked ? (
        <BrokenItemActions
          key={`${picked.item_kind}-${picked.id}`}
          itemKind={picked.item_kind}
          itemId={picked.id}
        />
      ) : (
        <p className="tv-repair-pick-prompt">{t("inventory.repair.pickPrompt")}</p>
      )}
    </div>
  );
}

export function RepairClaimsTab({
  section,
  onSectionChange,
}: {
  section: RepairSectionId;
  onSectionChange: (section: RepairSectionId) => void;
}) {
  const t = useT();
  const [openCount, setOpenCount] = useState<number | null>(null);
  const [historyCount, setHistoryCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    claimsApi
      .getClaimsStats()
      .then((stats) => {
        if (!cancelled) setOpenCount(stats.open_claims_count);
      })
      .catch(() => undefined);
    listClaims(true)
      .then((rows) => {
        if (!cancelled) {
          setHistoryCount(rows.filter(isHistoryClaim).length);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const sections: {
    id: RepairSectionId;
    label: string;
    count: number | null;
    body: ReactNode;
  }[] = [
    {
      id: "new",
      label: t("inventory.repair.new"),
      count: null,
      body: <NewRepairPanel />,
    },
    {
      id: "open",
      label: t("inventory.repair.open"),
      count: openCount,
      body: <ClaimsList view="open" />,
    },
    {
      id: "history",
      label: t("inventory.repair.history"),
      count: historyCount,
      body: <ClaimsList view="history" />,
    },
  ];
  const active = sections.find((s) => s.id === section) ?? sections[0];

  return (
    <SideList
      listLabel={t("inventory.view.repairClaims")}
      list={
        <>
          {sections.map((s) => (
            <SideListRow
              key={s.id}
              title={s.label}
              selected={s.id === active.id}
              onSelect={() => onSectionChange(s.id)}
              trailing={s.count !== null ? s.count : undefined}
            />
          ))}
        </>
      }
      panel={<Panel title={active.label}>{active.body}</Panel>}
    />
  );
}
