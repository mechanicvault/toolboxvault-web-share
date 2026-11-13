/**
 * /3dprints/upload — the publish wizard (Downloads
 * Part 2, owner order 2026-11-08), rebuilt as a designed
 * step flow (Sweep C1, finding 07-F4 — presentation only).
 *
 * The page wears the Prints section header (the shared
 * SectionPageHeader kit, as the Browse page does) and walks
 * the inspection wizard's proven pattern: a "Step N of 3"
 * progress line, one topic per screen, and labelled Back /
 * Next doors. Step 1 asks the owner's question: NEW FILE or
 * UPDATE TO AN EXISTING FILE? An update picks from the
 * publisher's OWN files only and adds a version — the number
 * rises, the old versions stay on the record, still
 * downloadable. Step 2 is the file itself: a new file takes
 * title, description, the shelf's own category set, the
 * print file (.stl/.3mf/.obj), an optional STEP, and a
 * version note; an update takes the same file seats and
 * note. Step 3 is photos and video, the topic rule, and the
 * publish door. The topic rule (mechanic / tool / toolbox
 * only) is stated on the form. Every field, limit, and help
 * string is the pre-remake page's, word for word — only the
 * presentation changed.
 *
 * File picks ride designed doors (FileDoor): a drop zone
 * that says what it takes in words, never the browser's raw
 * "Choose File" widget, and a picked file shows its name,
 * size, and Ready state with a remove door.
 *
 * Photos and the video are STAGED in the form (owner report
 * 2026-11-10: the old single preview-photo seat let a
 * publisher pick just one photo and offered no video at
 * all): the photos seat takes several photos in one pick, up
 * to the listing's set of five — staged thumbnails with a
 * remove button each, the first photo the cover — and the
 * video seat takes the listing's one video (30 seconds max,
 * its length verified on the server at upload). On publish
 * the listing is created first, then the staged media attach
 * one by one through the same doors the edit page uses; a
 * file that fails lands in a warning naming it, never in
 * silence. An update stages media the same way — new photos
 * APPEND to the set (they never displace the cover), and a
 * listing that already has a video says so instead of
 * offering a second seat.
 *
 * Registered only: the route rides RequireAuth + the prints
 * feature module gate in the registry; the server enforces
 * both again, plus the community-block door.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  Alert,
  Button,
  FormField,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { SectionPageHeader } from "../../components/SectionPageHeader";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import {
  addPrintPhoto,
  addPrintVideo,
  getMyPrints,
  getPrint,
  mediaUrl,
  publishPrint,
  publishPrintUpdate,
} from "./api";
import { FileDoor, PickedFileRow } from "./FileDoor";
import { PRINT_CATEGORIES, type PrintDetail, type PrintFileRow } from "./types";
import "./prints.css";

/* Each seat takes ONE family of files. The picker's accept
 * filter is the first guard; these seat checks are the second —
 * a file forced past the picker (the dialog's "All files" view)
 * is refused on the spot, in its seat, instead of after a
 * submit round trip. The server validates the bytes themselves
 * last, and its word is final. */
const PRINT_EXTS = [".stl", ".3mf", ".obj"];
const STEP_EXTS = [".step", ".stp"];
const PHOTO_EXTS = [".jpg", ".jpeg", ".png", ".webp"];
const VIDEO_EXTS = [".mp4", ".webm", ".mov"];
/** The listing's photo set (the server's PHOTO_MAX_COUNT)
 * and the per-photo size limit (the server's
 * PHOTO_MAX_BYTES) — the seats refuse at the same lines the
 * server holds, so nothing stages that cannot land. */
const PHOTO_MAX = 5;
const PHOTO_MAX_BYTES = 10 * 1024 * 1024;

/** A photo picked in the form, before the listing exists —
 * the site's staged-file pattern (the inventory picker's
 * shape): held locally with a live preview, uploaded against
 * the new listing the moment it exists. */
interface StagedPhoto {
  id: string;
  file: File;
  url: string;
}

/** The one staged video, same pattern. */
interface StagedVideo {
  file: File;
  url: string;
}

let stagedSeq = 0;

function fileExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export default function PrintUploadPage() {
  return (
    <RequireAuth>
      <PrintUploadForm />
    </RequireAuth>
  );
}

function PrintUploadForm() {
  const t = useT();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const wantedUpdate = params.get("update") ?? "";

  const [mode, setMode] = useState<"new" | "update" | null>(wantedUpdate ? "update" : null);
  /* The wizard's screens after the choice: 2 = the file,
   * 3 = photos and video. The choice itself is step 1. */
  const [formStep, setFormStep] = useState<2 | 3>(2);
  const [myFiles, setMyFiles] = useState<PrintFileRow[] | null>(null);
  const [targetId, setTargetId] = useState(wantedUpdate);
  const [targetDetail, setTargetDetail] = useState<PrintDetail | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<string>(PRINT_CATEGORIES[0]);
  const [note, setNote] = useState("");
  const [printFile, setPrintFile] = useState<File | null>(null);
  const [stepFile, setStepFile] = useState<File | null>(null);
  const [photos, setPhotos] = useState<StagedPhoto[]>([]);
  const [video, setVideo] = useState<StagedVideo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /* Seat-level refusals (owner report, 2026-11-08: the three
   * bare inputs gave no sign of what each seat had taken —
   * the media seats now also show what they hold). */
  const [printError, setPrintError] = useState<string | null>(null);
  const [stepError, setStepError] = useState<string | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);

  /* The update target's current set: staged photos count
   * against the room it has left, and a listing that already
   * carries a video gets a note instead of a second seat. */
  const existingMedia = mode === "update" ? (targetDetail?.media ?? []) : [];
  const existingPhotos = existingMedia.filter((m) => m.kind === "photo");
  const existingVideo = existingMedia.find((m) => m.kind === "video") ?? null;
  const photoRoom = PHOTO_MAX - existingPhotos.length - photos.length;

  useEffect(() => {
    if (mode !== "update" || !targetId) {
      setTargetDetail(null);
      return;
    }
    let live = true;
    getPrint(targetId)
      .then((d) => {
        if (live) setTargetDetail(d);
      })
      .catch(() => {
        if (live) setTargetDetail(null);
      });
    return () => {
      live = false;
    };
  }, [mode, targetId]);

  /* Staged object URLs die with their stage: revoked when a
   * file is removed or the stage clears, and the survivors on
   * unmount (the ref mirrors the latest stage for that last
   * pass). */
  const stagedRef = useRef<{ photos: StagedPhoto[]; video: StagedVideo | null }>({
    photos: [],
    video: null,
  });
  useEffect(() => {
    stagedRef.current = { photos, video };
  }, [photos, video]);
  useEffect(
    () => () => {
      stagedRef.current.photos.forEach((p) => URL.revokeObjectURL(p.url));
      if (stagedRef.current.video) URL.revokeObjectURL(stagedRef.current.video.url);
    },
    [],
  );

  function clearStaged() {
    photos.forEach((p) => URL.revokeObjectURL(p.url));
    if (video) URL.revokeObjectURL(video.url);
    setPhotos([]);
    setVideo(null);
    setPhotoError(null);
    setVideoError(null);
  }

  function chooseMode(next: "new" | "update" | null) {
    clearStaged();
    setFormStep(2);
    setError("");
    setMode(next);
  }

  function chooseTarget(id: string) {
    clearStaged();
    setTargetId(id);
  }

  function pickPrint(file: File | null) {
    if (file && !PRINT_EXTS.includes(fileExt(file.name))) {
      setPrintFile(null);
      setPrintError(t("prints.upload.printWrongType"));
      return;
    }
    setPrintError(null);
    setPrintFile(file);
  }

  function pickStep(file: File | null) {
    if (file && !STEP_EXTS.includes(fileExt(file.name))) {
      setStepFile(null);
      setStepError(t("prints.upload.stepWrongType"));
      return;
    }
    setStepError(null);
    setStepFile(file);
  }

  /** One pick can carry the whole set: every file is checked
   * in its seat (type, then size, then the room the listing
   * has left) — the good ones stage, the refused ones name
   * their reason on the seat. */
  function pickPhotos(list: FileList | null) {
    if (!list) return;
    let problem: string | null = null;
    let room = PHOTO_MAX - existingPhotos.length - photos.length;
    const staged: StagedPhoto[] = [];
    for (const file of Array.from(list)) {
      if (!PHOTO_EXTS.includes(fileExt(file.name))) {
        problem ??= t("prints.upload.photoWrongType");
        continue;
      }
      if (file.size > PHOTO_MAX_BYTES) {
        problem ??= t("prints.upload.photoTooLarge");
        continue;
      }
      if (room <= 0) {
        problem ??= t("prints.upload.photosFull");
        continue;
      }
      room -= 1;
      staged.push({
        id: `staged-${++stagedSeq}`,
        file,
        url: URL.createObjectURL(file),
      });
    }
    setPhotoError(problem);
    if (staged.length > 0) setPhotos((prev) => [...prev, ...staged]);
  }

  function removePhoto(id: string) {
    const target = photos.find((p) => p.id === id);
    if (target) URL.revokeObjectURL(target.url);
    setPhotos((prev) => prev.filter((p) => p.id !== id));
  }

  function pickVideo(file: File | null) {
    if (!file) return;
    if (!VIDEO_EXTS.includes(fileExt(file.name))) {
      setVideoError(t("prints.edit.videoWrongType"));
      return;
    }
    setVideoError(null);
    if (video) URL.revokeObjectURL(video.url);
    setVideo({ file, url: URL.createObjectURL(file) });
  }

  function removeVideo() {
    if (video) URL.revokeObjectURL(video.url);
    setVideo(null);
  }

  useEffect(() => {
    getMyPrints()
      .then((data) => setMyFiles(data.files.filter((f) => f.status === "live")))
      .catch(() => setMyFiles([]));
  }, []);

  const target = myFiles?.find((f) => f.id === targetId) ?? null;

  async function submit() {
    setError("");
    if (mode === "update" && !target) {
      setError(t("prints.upload.pickFirst"));
      return;
    }
    if (!printFile) {
      setError(t("prints.upload.needPrint"));
      return;
    }
    const form = new FormData();
    form.append("note", note);
    form.append("print_file", printFile);
    if (stepFile) form.append("step_file", stepFile);
    /* A NEW listing's first staged photo rides the publish
     * itself — the server seeds it as photo #1 (the cover) on
     * the same stored object, so the listing has its picture
     * from the moment it exists. An update sends none: its
     * staged photos append through the media door below, in
     * order, behind the set the listing already carries. */
    if (mode === "new" && photos.length > 0) {
      form.append("preview", photos[0].file);
    }
    setBusy(true);
    try {
      let saved;
      if (mode === "update" && target) {
        saved = await publishPrintUpdate(target.id, form);
      } else {
        form.append("title", title);
        form.append("description", description);
        form.append("category", category);
        saved = await publishPrint(form);
      }
      /* The media pass: the listing exists now, so the rest
       * of the staged set attaches through the edit page's
       * own doors, one at a time, in the staged order. A file
       * the server refuses (a video over 30 seconds is the
       * standing example) never fails the publish — it is
       * named in a warning, with its reason, and the member
       * lands on the listing to add it again. */
      const failed: string[] = [];
      const toAttach = mode === "new" ? photos.slice(1) : photos;
      for (const staged of toAttach) {
        try {
          await addPrintPhoto(saved.id, staged.file);
        } catch (err) {
          failed.push(
            err instanceof Error
              ? `${staged.file.name} — ${err.message}`
              : staged.file.name,
          );
        }
      }
      if (video && !existingVideo) {
        try {
          await addPrintVideo(saved.id, video.file);
        } catch (err) {
          failed.push(
            err instanceof Error ? `${video.file.name} — ${err.message}` : video.file.name,
          );
        }
      }
      if (failed.length > 0) {
        toast(`${failed.join("; ")} — ${t("prints.upload.mediaWarningTail")}`, {
          title: t("prints.upload.mediaWarningTitle"),
          tone: "warning",
          duration: 12000,
        });
      } else {
        toast(mode === "update" ? t("prints.upload.doneUpdate") : t("prints.upload.doneNew"));
      }
      navigate(`/3dprints/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  /* Step 2's Next door carries the old publish guards in
   * words: it stays shut until the step's requirement is met,
   * and the missing piece is named beside it. submit() keeps
   * the same guards as the backstop. */
  const step2Missing =
    mode === "new"
      ? !title.trim()
        ? t("prints.upload.needTitle")
        : !printFile
          ? t("prints.upload.needPrint")
          : null
      : !target
        ? t("prints.upload.pickFirst")
        : !printFile
          ? t("prints.upload.needPrint")
          : null;

  return (
    <div className="pr-page pr-upload-page">
      {/* The page header is the shared SectionPageHeader kit,
          the same seat the Browse page wears (Sweep C1): the
          module's parts artwork in the plate, the standing
          title and sub, and the one Actions dropdown — back
          to the shelf, and My Files. The prints module has no
          settings of its own, so the menu carries no Settings
          entry (the Browse page's standing finding). */}
      <SectionPageHeader
        thumb={<ArtIcon name="parts" size={96} />}
        title={t("prints.upload.title")}
        subtitle={t("prints.sub")}
        actions={
          <SettingsActionsMenu
            ariaLabel={t("prints.upload.title")}
            buttonLabel={t("inventory.actions")}
            entries={[
              {
                key: "shelf",
                label: t("prints.backToShelf"),
                run: () => navigate("/3dprints"),
              },
              {
                key: "my",
                label: t("prints.tab.my"),
                run: () => navigate("/3dprints#my"),
              },
            ]}
          />
        }
      />

      {mode === null && (
        <section className="pr-panel pr-step-panel" key="step1">
          <p className="pr-progress">
            {t("prints.upload.stepOf").replace("{step}", "1").replace("{total}", "3")}
          </p>
          <h2 className="pr-panel-title">{t("prints.upload.stepChoose")}</h2>
          <div className="pr-choice-grid">
            <button type="button" className="pr-choice" onClick={() => chooseMode("new")}>
              <strong>{t("prints.upload.newCard")}</strong>
              <span>{t("prints.upload.newCardBody")}</span>
              <span className="pr-choice-go">{t("prints.upload.tapToChoose")} →</span>
            </button>
            <button type="button" className="pr-choice" onClick={() => chooseMode("update")}>
              <strong>{t("prints.upload.updateCard")}</strong>
              <span>{t("prints.upload.updateCardBody")}</span>
              <span className="pr-choice-go">{t("prints.upload.tapToChoose")} →</span>
            </button>
          </div>
          <p className="pr-step-note pr-pick-hint">{t("prints.upload.pickHint")}</p>
        </section>
      )}

      {mode !== null && formStep === 2 && (
        <section className="pr-panel pr-step-panel" key="step2">
          <p className="pr-progress">
            {t("prints.upload.stepOf").replace("{step}", "2").replace("{total}", "3")}
          </p>
          <h2 className="pr-panel-title">
            {mode === "new" ? t("prints.upload.stepFileNew") : t("prints.upload.stepFileUpdate")}
          </h2>

          <div className="pr-upload-grid">
            <div className="pr-upload-col">
              {mode === "update" &&
                (myFiles === null ? (
                  <Spinner label={t("prints.loading")} />
                ) : myFiles.length === 0 ? (
                  <p className="pr-muted">{t("prints.upload.noFiles")}</p>
                ) : (
                  <FormField label={t("prints.upload.pickFile")}>
                    <Select value={targetId} onChange={(e) => chooseTarget(e.target.value)}>
                      <option value="">—</option>
                      {myFiles.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.title} (v{f.current_version})
                        </option>
                      ))}
                    </Select>
                  </FormField>
                ))}

              {mode === "new" && (
                <>
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
                </>
              )}
            </div>

            <div className="pr-upload-col">
              <FormField label={t("prints.upload.printFileLabel")} error={printError ?? undefined}>
                <>
                  <FileDoor
                    accept=".stl,.3mf,.obj"
                    onPick={(files) => pickPrint(files[0] ?? null)}
                    dropText={t("prints.upload.dropFile")}
                    buttonLabel={t("prints.upload.chooseFile")}
                  />
                  {printFile && (
                    <PickedFileRow
                      name={printFile.name}
                      size={printFile.size}
                      readyLabel={t("prints.upload.ready")}
                      removeLabel={t("prints.edit.remove")}
                      onRemove={() => pickPrint(null)}
                    />
                  )}
                </>
              </FormField>
              <FormField label={t("prints.upload.stepFileLabel")} error={stepError ?? undefined}>
                <>
                  <FileDoor
                    accept=".step,.stp"
                    onPick={(files) => pickStep(files[0] ?? null)}
                    dropText={t("prints.upload.dropFile")}
                    buttonLabel={t("prints.upload.chooseFile")}
                  />
                  {stepFile && (
                    <PickedFileRow
                      name={stepFile.name}
                      size={stepFile.size}
                      readyLabel={t("prints.upload.ready")}
                      removeLabel={t("prints.edit.remove")}
                      onRemove={() => pickStep(null)}
                    />
                  )}
                </>
              </FormField>
              <FormField label={t("prints.upload.noteLabel")}>
                <TextInput
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  maxLength={500}
                  placeholder={t("prints.upload.notePlaceholder")}
                />
              </FormField>
            </div>
          </div>

          <div className="pr-modal-actions">
            {step2Missing && <p className="pr-next-hint">{step2Missing}</p>}
            <Button variant="secondary" onClick={() => chooseMode(null)}>
              {t("prints.upload.back")}
            </Button>
            <Button disabled={step2Missing !== null} onClick={() => setFormStep(3)}>
              {t("prints.upload.next")}
            </Button>
          </div>
        </section>
      )}

      {mode !== null && formStep === 3 && (
        <section className="pr-panel pr-step-panel" key="step3">
          <p className="pr-progress">
            {t("prints.upload.stepOf").replace("{step}", "3").replace("{total}", "3")}
          </p>
          <h2 className="pr-panel-title">{t("prints.upload.stepMedia")}</h2>

          <div className="pr-upload-grid">
            <div className="pr-upload-col">
              <FormField
                label={`${t("prints.upload.photosLabel")} (${existingPhotos.length + photos.length} / ${PHOTO_MAX})`}
                error={photoError ?? undefined}
              >
                <>
                  <p className="pr-step-note">{t("prints.upload.photosNote")}</p>
                  {(existingPhotos.length > 0 || photos.length > 0) && (
                    <div className="pr-media-grid pr-media-grid-edit pr-staged-grid">
                      {existingPhotos.map((m, i) => (
                        <div key={m.id} className="pr-media-cell">
                          <div className="pr-media-tile pr-media-tile-static">
                            <img src={mediaUrl(targetId, m.id)} alt="" loading="lazy" />
                            {i === 0 && (
                              <span className="pr-media-cover">{t("prints.edit.cover")}</span>
                            )}
                          </div>
                          <p className="pr-staged-name">{t("prints.upload.photosOnListing")}</p>
                        </div>
                      ))}
                      {photos.map((p, i) => (
                        <div key={p.id} className="pr-media-cell">
                          <div className="pr-media-tile pr-media-tile-static">
                            <img src={p.url} alt="" />
                            {existingPhotos.length === 0 && i === 0 && (
                              <span className="pr-media-cover">{t("prints.edit.cover")}</span>
                            )}
                          </div>
                          <div className="pr-media-cell-actions">
                            <span className="pr-staged-name" title={p.file.name}>
                              {p.file.name}
                            </span>
                            <button
                              type="button"
                              className="tv-list-remove-btn pr-media-remove"
                              aria-label={t("prints.edit.remove")}
                              title={t("prints.edit.remove")}
                              onClick={() => removePhoto(p.id)}
                            >
                              {"−"}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {photoRoom > 0 && (
                    <FileDoor
                      accept="image/png,image/jpeg,image/webp"
                      multiple
                      onPick={(files) => pickPhotos(files)}
                      dropText={t("prints.upload.dropPhotos")}
                      buttonLabel={t("prints.upload.chooseFiles")}
                    />
                  )}
                </>
              </FormField>
            </div>

            <div className="pr-upload-col">
              <FormField label={t("prints.upload.videoLabel")} error={videoError ?? undefined}>
                <>
                  <p className="pr-step-note">{t("prints.edit.videoNote")}</p>
                  {existingVideo ? (
                    <p className="pr-muted">
                      {existingVideo.filename} — {t("prints.upload.videoOnListing")}
                    </p>
                  ) : video ? (
                    <div className="pr-staged-video">
                      <video
                        className="pr-staged-video-el"
                        src={video.url}
                        controls
                        preload="metadata"
                        playsInline
                      />
                      <div className="pr-media-cell-actions">
                        <span className="pr-staged-name" title={video.file.name}>
                          {video.file.name}
                        </span>
                        <button
                          type="button"
                          className="tv-list-remove-btn pr-media-remove"
                          aria-label={t("prints.edit.remove")}
                          title={t("prints.edit.remove")}
                          onClick={removeVideo}
                        >
                          {"−"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <FileDoor
                      accept="video/mp4,video/webm,video/quicktime,.mov"
                      onPick={(files) => pickVideo(files[0] ?? null)}
                      dropText={t("prints.upload.dropVideo")}
                      buttonLabel={t("prints.upload.chooseFile")}
                    />
                  )}
                </>
              </FormField>

              <div className="pr-summary">
                <h3 className="pr-summary-title">{t("prints.upload.summaryTitle")}</h3>
                <div className="pr-summary-row">
                  <span>{t("prints.upload.printFileLabel")}</span>
                  <strong>{printFile ? printFile.name : t("prints.upload.needPrint")}</strong>
                </div>
                {mode === "new" ? (
                  <>
                    <div className="pr-summary-row">
                      <span>{t("prints.upload.titleLabel")}</span>
                      <strong>{title.trim() || "—"}</strong>
                    </div>
                    <div className="pr-summary-row">
                      <span>{t("prints.upload.categoryLabel")}</span>
                      <strong>{t(`prints.category.${category}` as DictKey)}</strong>
                    </div>
                  </>
                ) : (
                  <div className="pr-summary-row">
                    <span>{t("prints.upload.pickFile")}</span>
                    <strong>{target ? `${target.title} (v${target.current_version})` : "—"}</strong>
                  </div>
                )}
                <div className="pr-summary-row">
                  <span>{t("prints.upload.photosLabel")}</span>
                  <strong>
                    {existingPhotos.length + photos.length} / {PHOTO_MAX}
                  </strong>
                </div>
                <div className="pr-summary-row">
                  <span>{t("prints.upload.videoLabel")}</span>
                  <strong>{existingVideo ? existingVideo.filename : video ? video.file.name : "—"}</strong>
                </div>
              </div>
            </div>
          </div>

          <p className="pr-rule">{t("prints.upload.rule")}</p>
          <p className="pr-muted">{t("prints.upload.sizeNote")}</p>
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="pr-modal-actions">
            <Button variant="secondary" onClick={() => setFormStep(2)}>
              {t("prints.upload.back")}
            </Button>
            <Button
              onClick={() => void submit()}
              loading={busy}
              disabled={mode === "new" ? !title.trim() : false}
            >
              {busy
                ? t("prints.upload.working")
                : mode === "new"
                  ? t("prints.upload.publish")
                  : t("prints.upload.publishUpdate")}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
