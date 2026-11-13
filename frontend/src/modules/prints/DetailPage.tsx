/**
 * /3dprints/:fileId — one print file's record page
 * (Downloads Part 2, owner order 2026-11-08).
 *
 * Main tab layout: the header (preview top-left — click for
 * the larger view — the facts on the right, ONE Actions
 * dropdown top-right), then real tabs: Details · Photos /
 * Video · Versions · Comments. The Photos / Video tab holds
 * the listing's showcase set; any tile opens the preview
 * viewer, which walks the whole set (owner, 2026-11-08).
 *
 * The access split is the owner's: everyone reads and
 * downloads the print file; STEP downloads, rating, comments,
 * and flags are registered-only — signed-out visitors meet
 * the sign-in prompt at those seats. Removal seats: the
 * publisher, and moderator_admin / god / operators for any
 * file (the server enforces both).
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  Button,
  Modal,
  Spinner,
  Tabs,
  TextArea,
  Toggle,
  VisitorPreviewBanner,
  useToast,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { formatDate } from "../../lib/format";
import {
  estimateMenuHeight,
  placeMenuInViewport,
  type MenuPlacement,
} from "../../lib/menuPlacement";
import { useAuth } from "../core";
import {
  getPrint,
  getPrintAsVisitor,
  getPrintComments,
  getPrintCommentsAsVisitor,
  mediaUrl,
  modRemovePrintComment,
  postPrintComment,
  previewUrl,
  printDownloadUrl,
  ratePrint,
  removePrintComment,
  setPrintFollow,
  stepDownloadUrl,
} from "./api";
import { MediaViewer, durationLabel } from "./MediaViewer";
import { FlagModal, RemoveFileModal } from "./modals";
import { StarsDisplay, StarsInput } from "./Stars";
import type { PrintComment, PrintDetail } from "./types";
import "./prints.css";

function categoryLabel(t: (k: DictKey) => string, key: string): string {
  return t(`prints.category.${key}` as DictKey);
}

function sizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export default function PrintDetailPage() {
  const t = useT();
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { fileId = "" } = useParams();
  const [detail, setDetail] = useState<PrintDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState("details");
  const [comments, setComments] = useState<PrintComment[] | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bigPreview, setBigPreview] = useState(false);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [followBusy, setFollowBusy] = useState(false);
  const [flagFile, setFlagFile] = useState(false);
  const [flagCommentId, setFlagCommentId] = useState<string | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  // "View as visitor" preview (Sweep D5): while on, `detail`
  // and `comments` hold the visitor-shaped payloads fetched
  // from the preview reads — the page renders exactly what a
  // signed-in non-owner sees because it renders THEIR data,
  // and every write seat on the page stands down.
  const [preview, setPreview] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuElRef = useRef<HTMLDivElement | null>(null);
  const [menuPos, setMenuPos] = useState<MenuPlacement | null>(null);

  const canModerate =
    !preview &&
    Boolean(
      user?.is_operator || user?.tier === "god" || user?.tier === "moderator_admin",
    );
  // Ownership comes from the payload's own `mine` flag — the
  // server's viewer-shaped verdict — never recomputed from
  // the publisher id here: in the visitor preview the payload
  // is a non-owner's, and every owner seat on this page (the
  // rate note, the media tab's add-yours door, the menu's
  // Edit / Remove) keys off this one flag (Sweep D5).
  const mine = Boolean(detail && user && detail.mine);
  const current = detail?.versions.find((v) => v.version_number === detail.current_version);

  const load = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([getPrint(fileId), getPrintComments(fileId)]);
      setDetail(d);
      setComments(c.comments);
      setMissing(false);
    } catch {
      setMissing(true);
    }
  }, [fileId]);

  useEffect(() => {
    void load();
  }, [load]);

  /* Enter the visitor preview: swap the page's data for the
   * preview fetches' payloads (the server shaped them for a
   * non-owner, so the owner furniture — Edit, Remove, the
   * "rate your own" note, the media tab's add-yours door —
   * leaves with the data, not by hiding). A failed fetch
   * leaves the owner view exactly as it was. */
  async function enterPreview() {
    setMenuOpen(false);
    try {
      const [d, c] = await Promise.all([
        getPrintAsVisitor(fileId),
        getPrintCommentsAsVisitor(fileId),
      ]);
      setDetail(d);
      setComments(c.comments);
      setPreview(true);
    } catch (err) {
      toast(err instanceof Error ? err.message : t("preview.loadError"));
    }
  }

  /* Exit: the owner's own payloads load FIRST and the mode
   * flips only once they are in hand, so the page never shows
   * owner controls over visitor data (or the reverse). */
  async function exitPreview() {
    await load();
    setPreview(false);
  }

  /* The Actions menu is portaled and placed by the shared
   * viewport rule (lib/menuPlacement, FIX 3, 2026-11-11): it
   * used to hang in-flow from the header cell, whose right edge
   * sits mid-screen at phone widths, so the menu opened ~100px
   * off the LEFT edge with Edit unreachable. Portaled at the
   * document root and clamped/flipped by the shared rule, it
   * always lands fully inside the viewport; its look
   * (.pr-actions-menu) is unchanged. */
  function placeMenu() {
    const wrap = menuRef.current;
    if (!wrap) return;
    const r = wrap.getBoundingClientRect();
    const rows =
      1 +
      (current?.has_step ? 1 : 0) +
      (mine ? 2 : 0) +
      (user && !mine && !preview ? 1 : 0) +
      (mine || canModerate ? 1 : 0);
    const measured = menuElRef.current?.scrollHeight;
    const estimated =
      measured && measured > 0 ? measured : estimateMenuHeight(rows);
    setMenuPos(
      placeMenuInViewport(r, { width: 240, estimatedHeight: estimated }),
    );
  }

  function toggleMenu() {
    if (!menuOpen) placeMenu();
    setMenuOpen((v) => !v);
  }

  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      const target = e.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (menuElRef.current?.contains(target)) return;
      setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", placeMenu);
    document.addEventListener("scroll", placeMenu, true);
    placeMenu();
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", placeMenu);
      document.removeEventListener("scroll", placeMenu, true);
    };
  }, [menuOpen]);

  async function pickStars(stars: number) {
    if (!detail || preview) return;
    try {
      const view = (await ratePrint(detail.id, stars)) as {
        average: number | null;
        count: number;
        my_rating: number;
      };
      setDetail({
        ...detail,
        rating: { average: view.average, count: view.count },
        my_rating: view.my_rating,
      });
      toast(t("prints.rate.saved"));
    } catch (err) {
      toast(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    }
  }

  async function postComment() {
    if (!detail || !draft.trim()) return;
    setPosting(true);
    try {
      await postPrintComment(detail.id, draft.trim());
      setDraft("");
      toast(t("prints.comments.posted"));
      const c = await getPrintComments(fileId);
      setComments(c.comments);
    } catch (err) {
      toast(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setPosting(false);
    }
  }

  async function dropComment(comment: PrintComment) {
    try {
      if (comment.mine) await removePrintComment(comment.id);
      else await modRemovePrintComment(comment.id, "");
      const c = await getPrintComments(fileId);
      setComments(c.comments);
    } catch (err) {
      toast(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    }
  }

  if (missing) {
    return (
      <div className="pr-page">
        <p className="pr-back">
          <Link to="/3dprints">← {t("prints.backToShelf")}</Link>
        </p>
        <section className="pr-panel">
          <p>{t("prints.notFound")}</p>
        </section>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="pr-page">
        <Spinner label={t("prints.loading")} />
      </div>
    );
  }

  const detailsTab = (
    <div className="pr-detail-grid">
      <section className="pr-panel">
        <h2 className="pr-panel-title">{t("prints.details.description")}</h2>
        <p className="pr-description">
          {detail.description || t("prints.details.noDescription")}
        </p>
        <h2 className="pr-panel-title">{t("prints.rate.title")}</h2>
        {mine ? (
          <p className="pr-muted">{t("prints.rate.own")}</p>
        ) : user ? (
          <div className="pr-rate-row">
            <StarsInput
              value={detail.my_rating ?? 0}
              onPick={(n) => void pickStars(n)}
              disabled={preview}
            />
            {detail.my_rating !== null && (
              <span className="pr-muted">
                {t("prints.rate.yours")}: {detail.my_rating} / 5
              </span>
            )}
          </div>
        ) : (
          <p className="pr-muted">
            <Link to="/login">{t("prints.signIn")}</Link> {t("prints.rate.signInRest")}
          </p>
        )}
      </section>
      <section className="pr-panel">
        <h2 className="pr-panel-title">{t("prints.details.facts")}</h2>
        {current && (
          <dl className="pr-facts-list">
            <div>
              <dt>{t("prints.details.printFile")}</dt>
              <dd>
                {current.print_filename} · {sizeLabel(current.print_size)}
              </dd>
            </div>
            <div>
              <dt>{t("prints.details.stepFile")}</dt>
              <dd>{current.has_step ? current.step_filename : t("prints.details.noStep")}</dd>
            </div>
          </dl>
        )}
        <div className="pr-detail-downloads">
          <a className="pr-download-btn" href={printDownloadUrl(detail.id)}>
            {t("prints.action.downloadPrint")}
          </a>
          {current?.has_step &&
            (user ? (
              <a className="pr-download-btn pr-download-step" href={stepDownloadUrl(detail.id)}>
                {t("prints.action.downloadStep")}
              </a>
            ) : (
              <p className="pr-muted">{t("prints.details.stepMembers")}</p>
            ))}
        </div>
        {detail.maker_links.length > 0 && (
          <>
            <h2 className="pr-panel-title">{t("prints.details.makerLinks")}</h2>
            <ul className="pr-links-list">
              {detail.maker_links.map((link) => (
                <li key={link.id} className="pr-link-row">
                  {/* The door is titled in words — the maker's
                      own label — never the raw URL (which broke
                      mid-word on phones); the address itself
                      rides the href and the hover title. */}
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="pr-link-label pr-link-url"
                    title={link.url}
                  >
                    {link.label || link.url}
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );

  const mediaTab = (
    <section className="pr-panel">
      {detail.media.length === 0 ? (
        <>
          <p className="pr-muted">{t("prints.media.empty")}</p>
          {mine && (
            <p>
              <Link className="pr-download-btn" to={`/3dprints/${detail.id}/edit`}>
                {t("prints.media.addYours")}
              </Link>
            </p>
          )}
        </>
      ) : (
        <div className="pr-media-grid">
          {detail.media.map((m, i) => (
            <button
              key={m.id}
              type="button"
              className="pr-media-tile"
              onClick={() => setViewerIndex(i)}
              aria-label={m.filename || t("prints.tab.media")}
            >
              {m.kind === "video" ? (
                <>
                  <video
                    className="pr-media-tile-video"
                    src={mediaUrl(detail.id, m.id)}
                    preload="metadata"
                    muted
                    playsInline
                  />
                  <span className="pr-media-play" aria-hidden="true">
                    ▶
                  </span>
                  {m.duration_seconds !== null && (
                    <span className="pr-media-duration">
                      {durationLabel(m.duration_seconds)}
                    </span>
                  )}
                </>
              ) : (
                <img src={mediaUrl(detail.id, m.id)} alt="" loading="lazy" />
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );

  const versionsTab = (
    <section className="pr-panel">
      <div className="pr-table-wrap">
        <table className="pr-table">
          <thead>
            <tr>
              <th scope="col">{t("prints.versions.col.version")}</th>
              <th scope="col">{t("prints.versions.col.date")}</th>
              <th scope="col">{t("prints.versions.col.note")}</th>
              <th scope="col">{t("prints.versions.col.file")}</th>
              <th scope="col" className="pr-num">{t("prints.versions.col.downloads")}</th>
              <th scope="col">
                <span className="pr-sr-only">{t("prints.versions.download")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.versions.map((v) => (
              <tr key={v.version_number}>
                <td>
                  v{v.version_number}
                  {v.version_number === detail.current_version && (
                    <span className="pr-current-chip">{t("prints.versions.current")}</span>
                  )}
                </td>
                <td>{formatDate(v.created_at)}</td>
                <td>{v.note}</td>
                <td>
                  {v.print_filename} · {sizeLabel(v.print_size)}
                </td>
                <td className="pr-num">{v.downloads.toLocaleString()}</td>
                <td className="pr-version-actions">
                  <a
                    className="pr-download-btn pr-download-sm"
                    href={printDownloadUrl(detail.id, v.version_number)}
                  >
                    {t("prints.versions.download")}
                  </a>
                  {v.has_step ? (
                    user ? (
                      <a
                        className="pr-download-btn pr-download-sm pr-download-step"
                        href={stepDownloadUrl(detail.id, v.version_number)}
                      >
                        {t("prints.versions.downloadStep")}
                      </a>
                    ) : (
                      <span className="pr-muted" title={t("prints.action.signInStep")}>
                        {t("prints.versions.downloadStep")}
                      </span>
                    )
                  ) : (
                    <span className="pr-muted">{t("prints.versions.noStep")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  const commentsTab = (
    <section className="pr-panel">
      {comments === null ? (
        <Spinner label={t("prints.loading")} />
      ) : comments.length === 0 ? (
        <p className="pr-muted">{t("prints.comments.empty")}</p>
      ) : (
        <ul className="pr-comments">
          {comments.map((comment) => (
            <li key={comment.id} className="pr-comment">
              <div className="pr-comment-head">
                <strong>{comment.author.display_name}</strong>
                <span className="pr-muted">{formatDate(comment.created_at)}</span>
                <span className="pr-comment-actions">
                  {user && !preview && !comment.mine && comment.status === "live" && (
                    <button
                      type="button"
                      className="pr-text-btn"
                      onClick={() => setFlagCommentId(comment.id)}
                    >
                      {t("prints.comments.flag")}
                    </button>
                  )}
                  {(comment.mine || canModerate) && comment.status === "live" && (
                    <button
                      type="button"
                      className="tv-list-remove-btn"
                      aria-label={t("prints.comments.remove")}
                      title={t("prints.comments.remove")}
                      onClick={() => void dropComment(comment)}
                    >
                      {"−"}
                    </button>
                  )}
                </span>
              </div>
              <p className="pr-comment-body">
                {comment.status === "live"
                  ? comment.body
                  : comment.status === "removed_author"
                    ? t("prints.comments.removedAuthor")
                    : t("prints.comments.removedMod")}
              </p>
            </li>
          ))}
        </ul>
      )}
      {user ? (
        <div className="pr-composer">
          <TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            maxLength={4000}
            placeholder={t("prints.comments.placeholder")}
            disabled={preview}
          />
          <Button
            onClick={() => void postComment()}
            loading={posting}
            disabled={preview || !draft.trim()}
          >
            {t("prints.comments.post")}
          </Button>
        </div>
      ) : (
        <p className="pr-muted">
          <Link to="/login">{t("prints.signIn")}</Link> {t("prints.comments.signIn")}
        </p>
      )}
    </section>
  );

  const tabs: TabItem[] = [
    { id: "details", label: t("prints.tab.details"), content: detailsTab },
    {
      id: "media",
      label: `${t("prints.tab.media")} (${detail.media.length})`,
      content: mediaTab,
    },
    { id: "versions", label: t("prints.tab.versions"), content: versionsTab },
    {
      id: "comments",
      label: `${t("prints.tab.comments")} (${detail.comment_count})`,
      content: commentsTab,
    },
  ];

  const menuStyle: CSSProperties | undefined = menuPos
    ? {
        top: menuPos.bottom !== undefined ? "auto" : menuPos.top,
        bottom: menuPos.bottom,
        left: menuPos.left,
        maxHeight: menuPos.maxHeight,
      }
    : undefined;

  return (
    <div className="pr-page">
      {preview && <VisitorPreviewBanner onExit={() => void exitPreview()} />}
      <p className="pr-back">
        <Link to="/3dprints">← {t("prints.backToShelf")}</Link>
      </p>
      <div className="pr-record-head">
        {/* The header picture is a door ONLY when it opens
            something (Sweep B7): a listing with no photos, no
            video and no preview used to render the same button
            over the placeholder art, and clicking it did
            nothing at all — a photo ritual for a file with
            none. With media, the viewer opens on the cover
            photo (or the first item, for a video-only set);
            with a preview but no media it opens the big
            preview; with neither, the plate is a plain plate. */}
        {detail.media.length > 0 || detail.has_preview ? (
          <button
            type="button"
            className="pr-record-thumb"
            onClick={() => {
              const coverIndex = detail.media.findIndex((m) => m.kind === "photo");
              if (coverIndex >= 0) setViewerIndex(coverIndex);
              else if (detail.media.length > 0) setViewerIndex(0);
              else setBigPreview(true);
            }}
            aria-label={detail.title}
          >
            {detail.has_preview ? (
              <img src={previewUrl(detail.id)} alt="" />
            ) : (
              <ArtIcon name="parts" size={44} />
            )}
          </button>
        ) : (
          <div className="pr-record-thumb pr-record-thumb--still">
            <ArtIcon name="parts" size={44} />
          </div>
        )}
        <div className="pr-record-main">
          <h1 className="pr-record-title">{detail.title}</h1>
          <dl className="pr-record-facts">
            <div>
              <dt>{t("prints.fact.publisher")}</dt>
              <dd>{detail.publisher.display_name}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.category")}</dt>
              <dd>{categoryLabel(t, detail.category)}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.version")}</dt>
              <dd>v{detail.current_version}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.rating")}</dt>
              <dd>
                {detail.rating.count > 0 && detail.rating.average !== null ? (
                  <span className="pr-rating-cell">
                    <StarsDisplay average={detail.rating.average} />
                    <span>
                      {detail.rating.average.toFixed(1)} ({detail.rating.count}{" "}
                      {detail.rating.count === 1
                        ? t("prints.ratingWord")
                        : t("prints.ratingsWord")})
                    </span>
                  </span>
                ) : (
                  t("prints.noRatings")
                )}
              </dd>
            </div>
            <div>
              <dt>{t("prints.fact.downloads")}</dt>
              <dd>{detail.download_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.stepDownloads")}</dt>
              <dd>{detail.step_download_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.added")}</dt>
              <dd>{formatDate(detail.created_at)}</dd>
            </div>
            <div>
              <dt>{t("prints.fact.updated")}</dt>
              <dd>{formatDate(detail.updated_at)}</dd>
            </div>
          </dl>
        </div>
        <div className="pr-actions" ref={menuRef}>
          <Button
            variant="secondary"
            onClick={toggleMenu}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            {t("prints.actions")} ▾
          </Button>
          {menuOpen &&
            createPortal(
            <div
              className="pr-actions-menu pr-actions-menu--portal"
              role="menu"
              ref={menuElRef}
              style={menuStyle}
            >
              <a
                className="pr-actions-item"
                href={printDownloadUrl(detail.id)}
                onClick={() => setMenuOpen(false)}
              >
                {t("prints.action.downloadPrint")}
              </a>
              {current?.has_step &&
                (user ? (
                  <a
                    className="pr-actions-item"
                    href={stepDownloadUrl(detail.id)}
                    onClick={() => setMenuOpen(false)}
                  >
                    {t("prints.action.downloadStep")}
                  </a>
                ) : (
                  <Link
                    className="pr-actions-item"
                    to="/login"
                    onClick={() => setMenuOpen(false)}
                  >
                    {t("prints.action.signInStep")}
                  </Link>
                ))}
              {mine && (
                <button
                  type="button"
                  className="pr-actions-item"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate(`/3dprints/${detail.id}/edit`);
                  }}
                >
                  {t("prints.action.edit")}
                </button>
              )}
              {mine && !preview && (
                <button
                  type="button"
                  className="pr-actions-item"
                  onClick={() => void enterPreview()}
                >
                  {t("preview.viewAsVisitor")}
                </button>
              )}
              {user && !mine && !preview && (
                <button
                  type="button"
                  className="pr-actions-item"
                  onClick={() => {
                    setMenuOpen(false);
                    setFlagFile(true);
                  }}
                >
                  {t("prints.action.flag")}
                </button>
              )}
              {(mine || canModerate) && (
                <button
                  type="button"
                  className="pr-actions-item pr-actions-danger"
                  onClick={() => {
                    setMenuOpen(false);
                    setRemoveOpen(true);
                  }}
                >
                  {t("prints.action.remove")}
                </button>
              )}
            </div>,
            document.body,
          )}
        </div>
      </div>

      {/* Per-file update opt-in (sweep E4): the follow switch
          rides under the header, above the tabs, so its state
          is visible from every tab. Signed-in non-publishers
          only — the publisher never follows their own file,
          and visitors get no dead control. */}
      {user && !mine && !preview ? (
        <div className="ca-alert-row">
          <div className="ca-alert-text">
            <p className="ca-alert-name">{t("prints.follow")}</p>
            <p className="ca-alert-help">{t("prints.followHelp")}</p>
          </div>
          <Toggle
            checked={detail.following}
            disabled={followBusy}
            ariaLabel={t("prints.follow")}
            onChange={(next) => {
              setFollowBusy(true);
              setPrintFollow(detail.id, next)
                .then((saved) =>
                  setDetail((d) => (d ? { ...d, following: saved.following } : d)),
                )
                .catch(() =>
                  toast(t("settings.notifications.saveFailed"), { tone: "danger" }),
                )
                .finally(() => setFollowBusy(false));
            }}
          />
        </div>
      ) : null}

      <Tabs tabs={tabs} activeId={tab} onChange={setTab} />

      <Modal open={bigPreview} onClose={() => setBigPreview(false)} title={detail.title}>
        <img className="pr-big-preview" src={previewUrl(detail.id, "display")} alt={detail.title} />
      </Modal>
      <MediaViewer
        fileId={detail.id}
        title={detail.title}
        media={detail.media}
        index={viewerIndex}
        onClose={() => setViewerIndex(null)}
        onIndex={setViewerIndex}
      />
      <FlagModal open={flagFile} onClose={() => setFlagFile(false)} fileId={detail.id} />
      <FlagModal
        open={flagCommentId !== null}
        onClose={() => setFlagCommentId(null)}
        commentId={flagCommentId ?? undefined}
      />
      <RemoveFileModal
        open={removeOpen}
        onClose={() => setRemoveOpen(false)}
        fileId={detail.id}
        moderator={canModerate && !mine}
        onRemoved={() => navigate("/3dprints")}
      />
    </div>
  );
}
