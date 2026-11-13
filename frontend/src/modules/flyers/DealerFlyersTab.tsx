import { useCallback, useEffect, useState } from "react";
import { EmptyState, LinkButton, Panel, Spinner } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { companyFlyers } from "./api";
import { SourcePanel } from "./SourcePanel";
import { sourceTitle, type CompanyFlyers } from "./types";

/**
 * The dealer page's Flyers tab (owner order, 2026-11-05 #10):
 * this company's flyer spots as clean blocks — the company's
 * own spot first, then each agent's — with the current flyer
 * and history per spot, and the posting controls for users
 * with rights (postable spots not yet opened, or spots the
 * viewer controls but isn't a connected viewer of, ride at
 * the end). A read failure or an empty company simply leaves
 * the blocks absent — the tab itself only exists while the
 * flyers module is effective for the viewer.
 */
export function DealerFlyersTab({
  companyId,
  companyName,
  asVisitor = false,
}: {
  companyId: string;
  companyName?: string;
  /** "View as visitor" preview (Sweep D5): read the tab's
   *  spots shaped for a member with no connection and no
   *  posting rights — the preview fetch, never the caller's
   *  own rights-bearing read. */
  asVisitor?: boolean;
}) {
  const t = useT();
  const [data, setData] = useState<CompanyFlyers | null>(null);
  const [epoch, setEpoch] = useState(0);

  const refresh = useCallback(() => setEpoch((e) => e + 1), []);

  useEffect(() => {
    let cancelled = false;
    companyFlyers(companyId, asVisitor)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData({ company_id: companyId, sources: [], postable: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, epoch, asVisitor]);

  if (data === null) return <Spinner label="Loading…" />;

  const shownKeys = new Set(data.sources.map((s) => s.key));
  const manageOnly = data.postable.filter((s) => !shownKeys.has(s.key));
  const blocks = [...data.sources, ...manageOnly];

  /* One honest empty line for the tab (Sweep B3, F8): when no
   * spot carries a flyer and the viewer posts nowhere here,
   * the tab says so ONCE — the per-spot blocks used to stack an
   * identical "No flyer up right now" panel for every empty
   * spot (the company spot and each agent spot saying the same
   * sentence, the agent spot's even naming the company). A
   * poster keeps the per-spot blocks: their post forms are the
   * manager, and an empty spot beside a posted one is honest
   * per-spot context. */
  const nothingPosted =
    blocks.length > 0 &&
    blocks.every(
      (s) => !s.current && s.history.length === 0 && !s.can_post,
    );

  if (blocks.length === 0 || nothingPosted) {
    /* The shared nothing-here-yet kit (Sweep A1, finding
       06-F3): the old tab was one muted line naming neither
       company nor poster. Now the sentence names this company
       and says who posts — the company or one of its agents —
       and the door is the Flyers page across all the viewer's
       dealers. (A poster seat never lands here: its postable
       spots ride in `blocks` above with their post form.) */
    const company =
      companyName ?? data.sources[0]?.company_name ?? t("flyers.title");
    return (
      <Panel>
        <EmptyState
          art="flyers"
          title={t("flyers.dealerEmptyTitle")}
          description={t("flyers.dealerEmpty").replace("{company}", company)}
          action={<LinkButton to="/flyers">{t("flyers.seeAll")}</LinkButton>}
        />
      </Panel>
    );
  }

  return (
    <div className="flyer-dealer-blocks">
      {blocks.map((source) => (
        <Panel key={source.key} title={sourceTitle(source)}>
          <SourcePanel source={source} onChanged={refresh} />
        </Panel>
      ))}
    </div>
  );
}
