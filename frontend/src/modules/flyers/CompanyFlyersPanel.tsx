import { useMemo, useState } from "react";
import {
  AttachmentViewer,
  Button,
  EmptyState,
  LinkButton,
  Panel,
  type ViewableAttachment,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import {
  EndedBadge,
  OpenFlyerButton,
  SpotManage,
  TakeDownButton,
  flyerAttachment,
  pagesLabel,
  windowLabel,
} from "./SourcePanel";
import { sourceTitle, type FlyerSource, type FlyerView } from "./types";

interface FlyerEntry {
  flyer: FlyerView;
  source: FlyerSource;
}

/** Who posted a flyer, as the row's fact: the agent's name
 *  for an agent spot; the company itself for the company's
 *  own spot. */
function postedBy(source: FlyerSource): string {
  return source.agent_name || source.company_name;
}

/** The upload date of a flyer (a real instant, rendered as
 *  the viewer's local calendar date). */
function uploadedLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

function CompanyFlyerRow({
  flyer,
  source,
  onPreview,
  onChanged,
}: {
  flyer: FlyerView;
  source: FlyerSource;
  onPreview: (() => void) | null;
  onChanged: () => void;
}) {
  const t = useT();
  return (
    <div
      className="flyer-company-row"
      {...(onPreview
        ? {
            role: "button" as const,
            tabIndex: 0,
            onClick: onPreview,
            onKeyDown: (e: React.KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onPreview();
              }
            },
          }
        : {})}
    >
      <span className="flyer-row-main">
        {flyer.thumb_url ? (
          <img className="flyer-row-thumb" src={flyer.thumb_url} alt="" />
        ) : null}
        <span className="flyer-row-text">
          <span className="flyer-row-labelrow">
            <span
              className="flyer-row-label"
              title={flyer.label || undefined}
            >
              {flyer.label || "—"}
            </span>
            {flyer.is_current ? (
              <span className="flyer-current-badge">
                {t("flyers.currentBadge")}
              </span>
            ) : null}
            <EndedBadge flyer={flyer} />
          </span>
          {/* Phone-only fact line (sweep B6 F6/F4): the columns
              fold away at <=640px, so the poster, the window,
              the pages and the upload date ride UNDER the
              headline instead of vanishing. */}
          <span className="flyer-row-sub">
            {postedBy(source)} · {windowLabel(flyer)} ·{" "}
            {pagesLabel(t, flyer.page_count)} ·{" "}
            {uploadedLabel(flyer.created_at)}
          </span>
        </span>
      </span>
      <span>{postedBy(source)}</span>
      <span>{windowLabel(flyer)}</span>
      <span>{pagesLabel(t, flyer.page_count)}</span>
      <span>{uploadedLabel(flyer.created_at)}</span>
      <span
        className="flyer-row-actions"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        {onPreview ? <OpenFlyerButton onOpen={onPreview} /> : null}
        {source.can_post ? (
          <TakeDownButton flyer={flyer} onDone={onChanged} />
        ) : null}
      </span>
    </div>
  );
}

/**
 * One company's flyer tab body (owner order, 2026-11-09):
 * a TRUE LIST of the company's flyers — every spot's current
 * flyer plus its past flyers (the backend already gates past
 * flyers on the spot's history_visible setting for viewers;
 * posters always see their own) — one flyer per row, facts
 * in columns, sorted by upload date, newest first. Clicking
 * a row opens the flyer in the preview window (the shared
 * AttachmentViewer) — the PDF is never embedded in the tab.
 *
 * Poster controls' home (the conformance map's lane call):
 * below the list, inside the same tab, one block per spot
 * the signed-in user may post to — each headed by the spot's
 * name so two spots of one company read apart, with the
 * spot's settings and the three-route post form behind the
 * spot's labelled "Post a flyer" door (sweep B6 F1: what is
 * posted leads; the composer never leads). The exact manage
 * door the dealer page's Flyers tab renders. Take-down rides
 * on the flyer's own row. Everything stays behind the same
 * can_post gate the backend computes; mechanics see the list
 * and nothing else.
 */
export function CompanyFlyersPanel({
  sources,
  onChanged,
  onPosted,
}: {
  sources: FlyerSource[];
  onChanged: () => void;
  /** Post-form success: defaults to onChanged; the page's
   *  below-tabs seat also selects the spot's company tab,
   *  which exists once the post lands. */
  onPosted?: () => void;
}) {
  const t = useT();
  const [preview, setPreview] = useState<FlyerView | null>(null);
  const [openSpot, setOpenSpot] = useState<string | null>(null);

  const entries = useMemo<FlyerEntry[]>(() => {
    const out: FlyerEntry[] = [];
    for (const source of sources) {
      if (source.current) out.push({ flyer: source.current, source });
      for (const flyer of source.history) {
        out.push({ flyer, source });
      }
    }
    // Newest posted first; the id breaks same-instant ties
    // the same way the backend's own history order does.
    out.sort((a, b) => {
      const byDate = b.flyer.created_at.localeCompare(a.flyer.created_at);
      return byDate !== 0 ? byDate : b.flyer.id.localeCompare(a.flyer.id);
    });
    return out;
  }, [sources]);

  const attachment: ViewableAttachment | null = preview
    ? flyerAttachment(preview, t("flyers.title"))
    : null;

  const manage = sources.filter((s) => s.can_post);

  return (
    <div className="flyer-source">
      <Panel>
        {entries.length > 0 ? (
          <div className="flyer-list">
            <div className="flyer-company-row flyer-company-row-head">
              <span>{t("flyers.colHeadline")}</span>
              <span>{t("flyers.colPostedBy")}</span>
              <span>
                {t("flyers.startsOn")} → {t("flyers.endsOn")}
              </span>
              <span>{t("flyers.colPages")}</span>
              <span>{t("flyers.colUploaded")}</span>
              <span />
            </div>
            {entries.map(({ flyer, source }) => (
              <CompanyFlyerRow
                key={flyer.id}
                flyer={flyer}
                source={source}
                onPreview={
                  flyer.pdf_url ? () => setPreview(flyer) : null
                }
                onChanged={onChanged}
              />
            ))}
          </div>
        ) : (
          /* The shared nothing-here-yet kit (Sweep A1): the
             sentence names this company and who posts for it;
             a poster's door opens the manage block below, a
             viewer's door is the Flyers page across all their
             dealers. */
          <EmptyState
            art="flyers"
            title={t("flyers.dealerEmptyTitle")}
            description={t(
              manage.length > 0
                ? "flyers.dealerEmptyPoster"
                : "flyers.dealerEmpty",
            ).replace(
              "{company}",
              sources[0]?.company_name ?? t("flyers.title"),
            )}
            action={
              manage.length > 0 ? (
                <Button
                  type="button"
                  onClick={() => {
                    setOpenSpot(manage[0].key);
                    document
                      .getElementById("flyer-company-post")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  {t("flyers.postTitle")}
                </Button>
              ) : (
                <LinkButton to="/flyers">{t("flyers.seeAll")}</LinkButton>
              )
            }
          />
        )}
      </Panel>

      {manage.map((source, index) => (
        <div
          key={source.key}
          className="flyer-source"
          {...(index === 0 ? { id: "flyer-company-post" } : {})}
        >
          <h3 className="flyer-spot-title">{sourceTitle(source)}</h3>
          <SpotManage
            source={source}
            onChanged={onChanged}
            onPosted={onPosted}
            open={openSpot === source.key}
            onToggle={() =>
              setOpenSpot(openSpot === source.key ? null : source.key)
            }
          />
        </div>
      ))}

      <AttachmentViewer
        attachment={attachment}
        onClose={() => setPreview(null)}
      />
    </div>
  );
}
