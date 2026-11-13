import { useState } from "react";
import {
  Alert,
  AttachmentViewer,
  Button,
  Checkbox,
  DatePicker,
  EmptyState,
  FormField,
  LinkButton,
  Panel,
  type ViewableAttachment,
} from "../../components";
import { ApiError } from "../../lib/api";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import {
  createSource,
  deleteFlyer,
  postLink,
  postPdfUpload,
  postPhotos,
  updateSource,
} from "./api";
import { ScanEditor } from "./ScanEditor";
import type { FlyerSource, FlyerView, ScanPage } from "./types";

function fill(template: string, subs: Record<string, string>): string {
  let out = template;
  for (const [k, v] of Object.entries(subs)) out = out.replace(`{${k}}`, v);
  return out;
}

function isoPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function pagesLabel(t: ReturnType<typeof useT>, count: number): string {
  return count === 1
    ? t("flyers.pageOne")
    : fill(t("flyers.pages"), { count: String(count) });
}

/** One window day in the viewer's own date language — the
 *  same medium format the Uploaded column uses, never the
 *  raw stored ISO string (sweep 06-F7: two date languages in
 *  one row read as a bug). The stored value is a plain
 *  calendar day, so it is parsed as a local date, not an
 *  instant. */
export function fmtDay(isoDay: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay);
  if (!m) return isoDay;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function windowLabel(flyer: FlyerView): string {
  return `${fmtDay(flyer.starts_on)} → ${fmtDay(flyer.ends_on)}`;
}

/** A flyer whose window has closed (and which is not the
 *  current one) says so — sweep 06-F7: past flyers used to be
 *  distinguishable only by LACKING the Current pill. */
export function flyerEnded(flyer: FlyerView): boolean {
  if (flyer.is_current) return false;
  return flyer.ends_on < new Date().toISOString().slice(0, 10);
}

export function EndedBadge({ flyer }: { flyer: FlyerView }) {
  const t = useT();
  if (!flyerEnded(flyer)) return null;
  return <span className="flyer-ended-badge">{t("flyers.endedBadge")}</span>;
}

/** The preview-window attachment for one flyer — the ONE
 *  way a flyer opens, in every seat (sweep B6 F3/F5). */
export function flyerAttachment(
  flyer: FlyerView,
  fallbackName: string,
): ViewableAttachment | null {
  if (!flyer.pdf_url) return null;
  return {
    key: flyer.id,
    filename: flyer.label || fallbackName,
    kind: "Flyer",
    content_type: "application/pdf",
    size_bytes: 0,
    url: flyer.pdf_url,
  };
}

/** The labelled door on a flyer row/card: says in words that
 *  it opens the full flyer (the short label rides on phones,
 *  where the full words squeeze the headline out). */
export function OpenFlyerButton({
  onOpen,
}: {
  onOpen: () => void;
}) {
  const t = useT();
  return (
    <button type="button" className="flyer-open-btn" onClick={onOpen}>
      <span className="flyer-open-long">{t("flyers.openPdf")}</span>
      <span className="flyer-open-short">{t("flyers.openShort")}</span>
    </button>
  );
}

/** Take-down with an inline arm step (no modal for one row).
 *  Exported for the flyer page's company tabs, whose rows
 *  carry the same control for the poster's own flyers. */
export function TakeDownButton({ flyer, onDone }: { flyer: FlyerView; onDone: () => void }) {
  const t = useT();
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!armed) {
    return (
      <button
        type="button"
        className="tv-list-remove-btn"
        aria-label={`${t("flyers.delete")}: ${flyer.label}`}
        title={t("flyers.delete")}
        onClick={() => setArmed(true)}
      >
        {"−"}
      </button>
    );
  }
  return (
    <Button
      type="button"
      variant="danger"
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await deleteFlyer(flyer.id);
          onDone();
        } finally {
          setBusy(false);
          setArmed(false);
        }
      }}
    >
      {t("flyers.delete")}?
    </Button>
  );
}

function FlyerRow({
  flyer,
  canPost,
  onChanged,
  onPreview,
}: {
  flyer: FlyerView;
  canPost: boolean;
  onChanged: () => void;
  onPreview: (() => void) | null;
}) {
  const t = useT();
  return (
    <div
      className="flyer-row"
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
        {/* The company list's headline stack (label row over a
            phone fact line): on a phone the state pill wraps
            UNDER the headline instead of squeezing it, and the
            window + pages fold into the line below — the
            coordinator gate fix for the dealer tab's history
            rows, where the pill used to land on the dates and
            the headline collapsed to a stub. */}
        <span className="flyer-row-text">
          <span className="flyer-row-labelrow">
            <span className="flyer-row-label" title={flyer.label || undefined}>
              {flyer.label || "—"}
            </span>
            <EndedBadge flyer={flyer} />
          </span>
          <span className="flyer-row-sub">
            {windowLabel(flyer)} · {pagesLabel(t, flyer.page_count)}
          </span>
        </span>
      </span>
      <span>{windowLabel(flyer)}</span>
      <span>{pagesLabel(t, flyer.page_count)}</span>
      <span
        className="flyer-row-actions"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        {onPreview ? <OpenFlyerButton onOpen={onPreview} /> : null}
        {canPost ? <TakeDownButton flyer={flyer} onDone={onChanged} /> : null}
      </span>
    </div>
  );
}

/**
 * A poster's controls for one spot BEHIND their labelled
 * door (sweep B6 F1): what is POSTED leads every flyers
 * surface; the spot's settings and the three-route post form
 * ride closed until the poster opens "Post a flyer". Shared
 * by the dealer tab (SourcePanel) and the flyer page's
 * company tabs (CompanyFlyersPanel) so a spot is managed the
 * same way in both seats.
 */
export function SpotManage({
  source,
  onChanged,
  onPosted,
  open,
  onToggle,
  anchorId,
}: {
  source: FlyerSource;
  onChanged: () => void;
  onPosted?: () => void;
  open: boolean;
  onToggle: () => void;
  anchorId?: string;
}) {
  const t = useT();
  const bodyId = `flyer-manage-${source.key.replace(/[^a-zA-Z0-9-]/g, "-")}`;
  return (
    <div className="flyer-manage-block" {...(anchorId ? { id: anchorId } : {})}>
      <Button
        type="button"
        variant="secondary"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
      >
        {t("flyers.postTitle")}
      </Button>
      {open ? (
        <div className="flyer-manage-body" id={bodyId}>
          <SourceSettings source={source} onChanged={onChanged} />
          <PostFlyerForm
            source={source}
            onChanged={onPosted ?? onChanged}
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * One flyer source as a block: the current flyer, the history
 * per the source's setting, and — for users with posting
 * rights — the spot's manage door (settings + post form
 * behind it). This is the DEALER PAGE's Flyers tab treatment;
 * the flyer page's company tabs render CompanyFlyersPanel
 * instead, reusing this file's exported settings form, post
 * form, manage door and take-down control so a spot is
 * managed the same way in both seats. A flyer OPENS the same
 * way in both seats too (sweep B6 F3/F5): the shared preview
 * window (AttachmentViewer) — the PDF is never embedded in
 * the tab anymore.
 */
export function SourcePanel({
  source,
  onChanged,
}: {
  source: FlyerSource;
  onChanged: () => void;
}) {
  const t = useT();
  const [preview, setPreview] = useState<FlyerView | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const current = source.current;
  return (
    <div className="flyer-source">
      {current ? (
        <Panel title={t("flyers.current")}>
          <div className="flyer-current">
            {current.thumb_url ? (
              <img
                className={
                  current.pdf_url
                    ? "flyer-current-thumb is-openable"
                    : "flyer-current-thumb"
                }
                src={current.thumb_url}
                alt=""
                {...(current.pdf_url
                  ? { onClick: () => setPreview(current) }
                  : {})}
              />
            ) : null}
            <div className="flyer-current-meta">
              {current.label ? (
                <p className="flyer-current-label">{current.label}</p>
              ) : null}
              <p>
                {windowLabel(current)} · {pagesLabel(t, current.page_count)}
              </p>
              {current.pdf_url ? (
                <p>
                  <OpenFlyerButton onOpen={() => setPreview(current)} />
                </p>
              ) : null}
              {source.can_post ? (
                <TakeDownButton flyer={current} onDone={onChanged} />
              ) : null}
            </div>
          </div>
        </Panel>
      ) : (
        <Panel title={t("flyers.current")}>
          {/* The shared nothing-here-yet kit (Sweep A1, finding
              06-F3's sibling seat): the sentence names this
              spot's company and who posts for it; a poster's
              door opens the manage block below (rendered for
              can_post spots only), a viewer's is the Flyers
              page. */}
          <EmptyState
            art="flyers"
            title={t("flyers.dealerEmptyTitle")}
            description={t(
              source.can_post
                ? "flyers.dealerEmptyPoster"
                : "flyers.dealerEmpty",
            ).replace("{company}", source.company_name)}
            action={
              source.can_post ? (
                <Button
                  type="button"
                  onClick={() => {
                    setManageOpen(true);
                    document
                      .getElementById(`flyer-post-${source.key}`)
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
        </Panel>
      )}

      {source.history.length > 0 ? (
        <Panel title={t("flyers.history")}>
          <div className="flyer-list">
            <div className="flyer-row flyer-row-head">
              <span>{t("flyers.colHeadline")}</span>
              <span>{t("flyers.startsOn")} → {t("flyers.endsOn")}</span>
              <span>{t("flyers.colPages")}</span>
              <span />
            </div>
            {source.history.map((flyer) => (
              <FlyerRow
                key={flyer.id}
                flyer={flyer}
                canPost={source.can_post}
                onChanged={onChanged}
                onPreview={
                  flyer.pdf_url ? () => setPreview(flyer) : null
                }
              />
            ))}
          </div>
        </Panel>
      ) : null}

      {source.can_post ? (
        <SpotManage
          source={source}
          onChanged={onChanged}
          open={manageOpen}
          onToggle={() => setManageOpen((v) => !v)}
          anchorId={`flyer-post-${source.key}`}
        />
      ) : null}

      <AttachmentViewer
        attachment={
          preview ? flyerAttachment(preview, t("flyers.title")) : null
        }
        onClose={() => setPreview(null)}
      />
    </div>
  );
}

/** The spot's own settings (visibility, history visibility,
 *  standing address) — edited here in the tab, never on the
 *  Settings page (conformance map §7). Exported for the flyer
 *  page's company tabs. */
export function SourceSettings({
  source,
  onChanged,
}: {
  source: FlyerSource;
  onChanged: () => void;
}) {
  const t = useT();
  const [visible, setVisible] = useState(source.visible);
  const [historyVisible, setHistoryVisible] = useState(source.history_visible);
  const [standingUrl, setStandingUrl] = useState(source.standing_url);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (source.id === null) return null;

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await updateSource(source.id as string, {
        visible,
        history_visible: historyVisible,
        standing_url: standingUrl.trim(),
      });
      setSaved(true);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("home.widgetLoadFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("flyers.settings")}>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {saved ? <Alert tone="success">{t("flyers.settingsSaved")}</Alert> : null}
      <div className="flyer-settings">
        <Checkbox
          label={t("flyers.visible")}
          checked={visible}
          onChange={(e) => setVisible(e.target.checked)}
        />
        <Checkbox
          label={t("flyers.historyVisible")}
          checked={historyVisible}
          onChange={(e) => setHistoryVisible(e.target.checked)}
        />
        <FormField label={t("flyers.standingUrl")} hint={t("flyers.standingHelp")}>
          <input
            className="tv-input"
            type="url"
            value={standingUrl}
            placeholder="https://…"
            onChange={(e) => setStandingUrl(e.target.value)}
          />
        </FormField>
        <Button type="button" disabled={busy} onClick={() => void save()}>
          {t("flyers.saveSettings")}
        </Button>
      </div>
    </Panel>
  );
}

type Route = "link" | "upload" | "photos";

/** The three-route post form (link / PDF upload / page
 *  photos). Exported for the flyer page's company tabs. */
export function PostFlyerForm({
  source,
  onChanged,
}: {
  source: FlyerSource;
  onChanged: () => void;
}) {
  const t = useT();
  const [route, setRoute] = useState<Route>("link");
  const [label, setLabel] = useState("");
  const [startsOn, setStartsOn] = useState(isoPlus(0));
  const [endsOn, setEndsOn] = useState(isoPlus(6));
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pages, setPages] = useState<ScanPage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posted, setPosted] = useState(false);

  async function ensureSource(): Promise<string> {
    if (source.id) return source.id;
    const created = await createSource({
      kind: source.kind,
      company_id: source.company_id,
      agent_user_id: source.agent_user_id,
      private_agent_id: source.private_agent_id,
    });
    return created.id as string;
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setPosted(false);
    try {
      const sourceId = await ensureSource();
      const window_ = { label, starts_on: startsOn, ends_on: endsOn };
      if (route === "link") {
        await postLink(sourceId, { url: url.trim(), ...window_ });
      } else if (route === "upload") {
        if (!file) throw new Error(t("flyers.choosePdf"));
        await postPdfUpload(sourceId, file, window_);
      } else {
        if (pages.length === 0) throw new Error(t("flyers.addPhotos"));
        await postPhotos(sourceId, { pages, ...window_ });
      }
      setPosted(true);
      setLabel("");
      setUrl("");
      setFile(null);
      setPages([]);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("home.widgetLoadFailed"));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    !busy &&
    (route === "link"
      ? url.trim().length > 0
      : route === "upload"
        ? file !== null
        : pages.length > 0);

  return (
    <Panel title={t("flyers.postTitle")}>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {posted ? <Alert tone="success">{t("flyers.posted")}</Alert> : null}
      <div className="flyer-form">
        <div className="flyer-routes" role="tablist" aria-label={t("flyers.postTitle")}>
          {(
            [
              ["link", "flyers.routeLink"],
              ["upload", "flyers.routeUpload"],
              ["photos", "flyers.routePhotos"],
            ] as [Route, DictKey][]
          ).map(([value, key]) => (
            <Button
              key={value}
              type="button"
              size="sm"
              variant={route === value ? "primary" : "secondary"}
              onClick={() => setRoute(value)}
            >
              {t(key)}
            </Button>
          ))}
        </div>

        {route === "link" ? (
          <FormField label={t("flyers.linkUrl")} hint={t("flyers.linkHelp")}>
            <input
              className="tv-input"
              type="url"
              value={url}
              placeholder="https://…"
              onChange={(e) => setUrl(e.target.value)}
            />
          </FormField>
        ) : null}

        {route === "upload" ? (
          <FormField label={t("flyers.choosePdf")}>
            <input
              className="tv-input"
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </FormField>
        ) : null}

        {route === "photos" ? <ScanEditor onChange={setPages} /> : null}

        <FormField label={t("flyers.label")}>
          <input
            className="tv-input"
            type="text"
            value={label}
            placeholder={t("flyers.labelPlaceholder")}
            onChange={(e) => setLabel(e.target.value)}
          />
        </FormField>
        <div className="flyer-window">
          <FormField label={t("flyers.startsOn")}>
            <DatePicker value={startsOn} onChange={setStartsOn} />
          </FormField>
          <FormField label={t("flyers.endsOn")}>
            <DatePicker value={endsOn} onChange={setEndsOn} />
          </FormField>
        </div>
        <Button type="button" disabled={!canSubmit} onClick={() => void submit()}>
          {route === "link" ? t("flyers.fetchPost") : t("flyers.post")}
        </Button>
      </div>
    </Panel>
  );
}
