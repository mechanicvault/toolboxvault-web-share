/**
 * /3dprints/:fileId/edit — the publisher edits their own
 * LISTING (owner order 2026-11-08 22:20: "you should be able
 * to edit your entry to update photos and text etc").
 *
 * Title, description, category; the photo set (add / remove /
 * reorder — the first photo is the cover the shelf shows);
 * and the one showcase video (add / remove; 30 seconds max,
 * its length verified on the server at upload). Media changes
 * land the moment they're made; the text saves on its button —
 * and a successful save returns the publisher to the shelf at
 * /3dprints (owner order 2026-11-09), while a failed save
 * stays here with its error. NONE of it moves the file's
 * version — versions are the print/STEP update flow's alone,
 * and the page says so.
 *
 * Publisher-only: the server enforces it on every door; this
 * page additionally refuses to render the form for anyone
 * else. Maker profile links stay where they already live —
 * the My Files tab — and the page points there.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  Alert,
  FormField,
  Select,
  StickySaveButton,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { RequireAuth, useAuth } from "../core";
import {
  addPrintPhoto,
  addPrintVideo,
  getPrint,
  mediaUrl,
  removePrintMedia,
  reorderPrintMedia,
  updatePrintListing,
} from "./api";
import { FileDoor } from "./FileDoor";
import { durationLabel } from "./MediaViewer";
import { PRINT_CATEGORIES, type PrintDetail, type PrintMedia } from "./types";
import "./prints.css";

const PHOTO_EXTS = [".jpg", ".jpeg", ".png", ".webp"];
const VIDEO_EXTS = [".mp4", ".webm", ".mov"];
const PHOTO_MAX = 5;

function fileExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export default function PrintEditPage() {
  return (
    <RequireAuth>
      <PrintEditForm />
    </RequireAuth>
  );
}

function PrintEditForm() {
  const t = useT();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { fileId = "" } = useParams();
  const [detail, setDetail] = useState<PrintDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<string>(PRINT_CATEGORIES[0]);
  const [saving, setSaving] = useState(false);
  const [mediaBusy, setMediaBusy] = useState(false);
  const [error, setError] = useState("");
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await getPrint(fileId);
      setDetail(d);
      setTitle(d.title);
      setDescription(d.description);
      setCategory(d.category);
      setMissing(false);
    } catch {
      setMissing(true);
    }
  }, [fileId]);

  useEffect(() => {
    void load();
  }, [load]);

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
  if (!user || detail.publisher.user_id !== user.id) {
    return (
      <div className="pr-page">
        <p className="pr-back">
          <Link to={`/3dprints/${detail.id}`}>← {t("prints.edit.back")}</Link>
        </p>
        <section className="pr-panel">
          <p>{t("prints.edit.notYours")}</p>
        </section>
      </div>
    );
  }

  const media = detail.media;
  const photos = media.filter((m) => m.kind === "photo");
  const video = media.find((m) => m.kind === "video") ?? null;
  const coverId = photos[0]?.id ?? null;

  async function applyMedia(run: () => Promise<{ media: PrintMedia[] }>, done: string) {
    setMediaBusy(true);
    setError("");
    try {
      const resp = await run();
      setDetail({ ...detail!, media: resp.media });
      toast(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setMediaBusy(false);
    }
  }

  async function saveDetails() {
    setSaving(true);
    setError("");
    try {
      const saved = await updatePrintListing(detail!.id, {
        title: title.trim(),
        description: description.trim(),
        category,
      });
      setDetail(saved);
      toast(t("prints.edit.saved"));
      // Owner order 2026-11-09: a successful save returns the
      // publisher to the files listing, landing at the top
      // (ScrollManager puts fresh navigations at scroll 0).
      // Replace, like the tool/battery form pages' post-save
      // navigation, so Back doesn't reopen the finished edit.
      // A failed save never reaches here — it stays on this
      // page with its error, unchanged.
      navigate("/3dprints", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setSaving(false);
    }
  }

  /** One pick can carry several photos (owner report
   * 2026-11-10: the seat took one file per pick, so filling
   * the set meant five trips through the file dialog). The
   * good files upload one at a time, in pick order, each
   * landing the moment it arrives like a single pick always
   * did; a refusal (the set's cap is the standing one) stops
   * the pass and surfaces the server's own words, with the
   * photos that already landed kept. */
  async function pickPhotos(list: FileList | null) {
    if (!list || !detail) return;
    const files = Array.from(list);
    const good = files.filter((f) => PHOTO_EXTS.includes(fileExt(f.name)));
    setPhotoError(
      good.length < files.length ? t("prints.upload.photoWrongType") : null,
    );
    if (good.length === 0) return;
    setMediaBusy(true);
    setError("");
    let media = detail.media;
    let landed = false;
    for (const file of good) {
      try {
        const resp = await addPrintPhoto(detail.id, file);
        media = resp.media;
        landed = true;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t("prints.upload.errorGeneric"),
        );
        break;
      }
    }
    if (landed) {
      setDetail({ ...detail, media });
      toast(t("prints.edit.photoAdded"));
    }
    setMediaBusy(false);
  }

  function pickVideo(file: File | null) {
    if (!file) return;
    if (!VIDEO_EXTS.includes(fileExt(file.name))) {
      setVideoError(t("prints.edit.videoWrongType"));
      return;
    }
    setVideoError(null);
    void applyMedia(() => addPrintVideo(detail!.id, file), t("prints.edit.videoAdded"));
  }

  function move(item: PrintMedia, delta: number) {
    const ids = media.map((m) => m.id);
    const at = ids.indexOf(item.id);
    const swap = at + delta;
    if (at < 0 || swap < 0 || swap >= ids.length) return;
    [ids[at], ids[swap]] = [ids[swap], ids[at]];
    void applyMedia(
      () => reorderPrintMedia(detail!.id, ids),
      t("prints.edit.saved"),
    );
  }

  return (
    <div className="pr-page pr-upload-page">
      <p className="pr-back">
        <Link to={`/3dprints/${detail.id}`}>← {t("prints.edit.back")}</Link>
      </p>
      <h1 className="pr-title">{t("prints.edit.title")}</h1>
      <p className="pr-step-note">{t("prints.edit.versionNote")}</p>

      {error && <Alert tone="danger">{error}</Alert>}

      <section className="pr-panel">
        <h2 className="pr-panel-title">{t("prints.edit.detailsTitle")}</h2>
        <FormField label={t("prints.upload.titleLabel")}>
          <TextInput value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} />
        </FormField>
        <FormField label={t("prints.upload.descLabel")}>
          <TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            maxLength={4000}
          />
        </FormField>
        <FormField label={t("prints.upload.categoryLabel")}>
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            {PRINT_CATEGORIES.map((key) => (
              <option key={key} value={key}>
                {t(`prints.category.${key}` as DictKey)}
              </option>
            ))}
          </Select>
        </FormField>
        <div className="pr-modal-actions">
          {/* The floating save (dashboard-flare lane,
              2026-11-09): the details save sits at the TOP of
              a long page (photos, files, versions below) — its
              twin pins bottom-right once it scrolls away. */}
          <StickySaveButton onClick={() => void saveDetails()} loading={saving} disabled={!title.trim()}>
            {t("prints.edit.save")}
          </StickySaveButton>
        </div>
      </section>

      <section className="pr-panel">
        <h2 className="pr-panel-title">
          {t("prints.edit.photosTitle")} ({photos.length} / {PHOTO_MAX})
        </h2>
        <p className="pr-step-note">{t("prints.edit.photosNote")}</p>
        {media.length > 0 && (
          <div className="pr-media-grid pr-media-grid-edit">
            {media.map((m, i) => (
              <div key={m.id} className="pr-media-cell">
                <div className="pr-media-tile pr-media-tile-static">
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
                  {m.id === coverId && (
                    <span className="pr-media-cover">{t("prints.edit.cover")}</span>
                  )}
                </div>
                <div className="pr-media-cell-actions">
                  <button
                    type="button"
                    className="pr-text-btn"
                    disabled={mediaBusy || i === 0}
                    onClick={() => move(m, -1)}
                    aria-label={t("prints.edit.moveLeft")}
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    className="pr-text-btn"
                    disabled={mediaBusy || i === media.length - 1}
                    onClick={() => move(m, 1)}
                    aria-label={t("prints.edit.moveRight")}
                  >
                    →
                  </button>
                  <button
                    type="button"
                    className="tv-list-remove-btn pr-media-remove"
                    aria-label={t("prints.edit.remove")}
                    title={t("prints.edit.remove")}
                    disabled={mediaBusy}
                    onClick={() =>
                      void applyMedia(
                        () => removePrintMedia(detail.id, m.id),
                        m.kind === "video"
                          ? t("prints.edit.videoRemoved")
                          : t("prints.edit.photoRemoved"),
                      )
                    }
                  >
                    {"−"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {photos.length < PHOTO_MAX && (
          <FormField label={t("prints.edit.addPhotos")} error={photoError ?? undefined}>
            <FileDoor
              accept="image/png,image/jpeg,image/webp"
              multiple
              disabled={mediaBusy}
              onPick={(files) => void pickPhotos(files)}
              dropText={t("prints.upload.dropPhotos")}
              buttonLabel={t("prints.upload.chooseFiles")}
            />
          </FormField>
        )}
      </section>

      <section className="pr-panel">
        <h2 className="pr-panel-title">{t("prints.edit.videoTitle")}</h2>
        <p className="pr-step-note">{t("prints.edit.videoNote")}</p>
        {video ? (
          <p className="pr-muted">
            {video.filename}
            {video.duration_seconds !== null &&
              ` · ${durationLabel(video.duration_seconds)}`}{" "}
            — {t("prints.edit.videoReplaceHint")}
          </p>
        ) : (
          <>
            <p className="pr-muted">{t("prints.edit.noVideo")}</p>
            <FormField label={t("prints.edit.addVideo")} error={videoError ?? undefined}>
              <FileDoor
                accept="video/mp4,video/webm,video/quicktime,.mov"
                disabled={mediaBusy}
                onPick={(files) => pickVideo(files[0] ?? null)}
                dropText={t("prints.upload.dropVideo")}
                buttonLabel={t("prints.upload.chooseFile")}
              />
            </FormField>
          </>
        )}
      </section>

      <section className="pr-panel">
        <p className="pr-step-note">
          {t("prints.edit.linksNote")}{" "}
          <Link to="/3dprints">{t("prints.tab.my")}</Link>
        </p>
      </section>
    </div>
  );
}
