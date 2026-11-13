/**
 * /downloads — the downloads page (owner order 2026-11-08: the
 * bare lead-magnet door became AN ACTUAL PAGE).
 *
 * A main tab layout page like any other on the site: since
 * 2026-11-10 (owner, 11:40) it renders in the FULL app shell —
 * rail, header, the works — for signed-in users and visitors
 * alike; the 2026-10-30 stand-alone-branding exemption is
 * retired, and with it the page's own in-content lockup and
 * its "Visit the main site" door (a door to where the reader
 * already is). What still sets the page apart is only its
 * teaser-wall exemption: an unregistered visitor may VIEW it,
 * under the visitor restrictions the door audit verified.
 *
 * The page proper: the shared SectionPageHeader kit (owner
 * conversion, 2026-11-10 — downloads art plate, title,
 * standing tagline, honest facts read from the shelves
 * themselves: how many documents, print files, and wallpapers
 * are up — and the page's unique-visitor count (the
 * POST /visit number) rides as the fourth fact), then REAL
 * Steel tabs — About first, then Documents, the 3D Print
 * Files door, and Wallpaper (Part 3, 2026-11-08): a gallery
 * of in-house HD artwork, each piece in desktop / tablet /
 * phone sizes on the same counted download path as the
 * documents. No Actions menu: the page owns no settings
 * and has no page-level commands — every control lives in its
 * tabs — and it renders identical for every seat, signed out
 * included, so the kit's Actions seat stays empty by the
 * kit's own contract.
 *
 * Everything here is public and free: no account, no email, no
 * gate anywhere. The old page made the inventory sheet depend
 * on an email signup — that requirement is GONE (owner order);
 * the generic sheet is a Documents row like every other file,
 * served by GET /api/downloads/files/tool-inventory — the very
 * bytes the old page handed out. One row differs (2026-11-09):
 * the inspection checklist's action is Customize, opening the
 * wizard that builds the visitor's own checklist PDF.
 *
 * The About tab carries ONE email seat (owner order 2026-11-08):
 * a voluntary news signup under the how-it-works copy, posting
 * to the same subscribe endpoint the old page used. The
 * never-sold promise stands ONLY at that field — on a page that
 * asks for no email, the warning block contradicted the page's
 * own "no email needed" word, so the block came off.
 */

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert,
  Button,
  FileTypeArt,
  FormField,
  Modal,
  SearchBar,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  TextInput,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useLocale, useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { ContentAlertToggle } from "./contentAlerts";
import { DownloadsConverter } from "./DownloadsConverter";
import { InspectionWizard } from "./InspectionWizard";
import "./downloads.css";

type TabId = "about" | "documents" | "wallpapers";

/** The 3D Print Files tab is a DOOR, not a panel (Downloads
 * Part 2, 2026-11-08 — the Help → How-to Videos pattern): the
 * shelf is its own page at /3dprints, and choosing the
 * tab navigates there. */
const PRINTS_PATH = "/3dprints";

const HASH_TO_TAB: Record<string, TabId> = {
  "#about": "about",
  "#documents": "documents",
  "#wallpapers": "wallpapers",
};

interface CatalogFile {
  key: string;
  format: string;
  filename: string;
  download_count: number;
}

/** The voluntary news signup (owner order 2026-11-08): the one
 * seat on this page that asks for an email, so it is the one
 * seat where the standing never-sold promise (owner-approved
 * 2026-10-28, verbatim, "Ever." in its bold-orange emphasis)
 * belongs — right at the field.
 *
 * Posts to the same /api/downloads/subscribe endpoint and store
 * the old page's signup used, with source "downloads-news" so
 * the list records where the signup came from. The endpoint
 * answers the same for new and already-listed addresses (no
 * membership oracle), so the done message says the same thing
 * either way. No confirmation email is sent by that machinery,
 * and the copy promises none. */
function NewsSignup() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending || done) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch("/api/downloads/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), source: "downloads-news" }),
      });
      if (res.status === 422) {
        setError(t("downloads.news.invalid"));
        return;
      }
      if (!res.ok) throw new Error("bad");
      setDone(true);
    } catch {
      setError(t("downloads.news.failed"));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="dl-panel dl-news">
      <h3>{t("downloads.news.title")}</h3>
      <p>{t("downloads.news.body")}</p>
      {done ? (
        <p className="dl-news-done" role="status">
          {t("downloads.news.done")}
        </p>
      ) : (
        <form className="dl-news-form" onSubmit={submit} noValidate>
          <FormField
            label={t("downloads.news.label")}
            htmlFor="dl-news-email"
            error={error ?? undefined}
          >
            <TextInput
              id="dl-news-email"
              type="email"
              autoComplete="email"
              placeholder={t("downloads.news.placeholder")}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </FormField>
          <Button type="submit" disabled={sending}>
            {sending ? t("downloads.news.sending") : t("downloads.news.button")}
          </Button>
        </form>
      )}
      <p className="dl-news-promise">
        {t("downloads.promise.never")} <span className="dl-ever">{t("downloads.promise.ever")}</span>
      </p>
    </section>
  );
}

function AboutTab({ onOpen }: { onOpen: (id: string) => void }) {
  const t = useT();
  /* Each shelf card is a real door to its shelf (Sweep B7):
   * the cards always read as clickable — bordered panels with
   * the main highlight treatment — but clicking used to do
   * nothing, sending the reader hunting for the tab strip.
   * The doors ride the page's own tab picking, so Documents
   * and Wallpaper open their tabs and 3D Print Files follows
   * its standing door to /3dprints. */
  const shelves = [
    { icon: "reports" as const, target: "documents", title: t("downloads.about.docsTitle"), body: t("downloads.about.docsBody") },
    { icon: "parts" as const, target: "prints", title: t("downloads.about.printsTitle"), body: t("downloads.about.printsBody") },
    { icon: "videos" as const, target: "wallpapers", title: t("downloads.about.wallpaperTitle"), body: t("downloads.about.wallpaperBody") },
  ];
  return (
    <div className="dl-about">
      <section className="dl-panel">
        <h2>{t("downloads.about.title")}</h2>
        <p className="dl-lede">{t("downloads.about.lede")}</p>
        <h3>{t("downloads.about.howTitle")}</h3>
        <ol className="dl-how">
          <li>{t("downloads.about.how1")}</li>
          <li>{t("downloads.about.how2")}</li>
          <li>{t("downloads.about.how3")}</li>
        </ol>
      </section>
      <NewsSignup />
      <div className="dl-shelves">
        {shelves.map((shelf) => (
          <button
            key={shelf.title}
            type="button"
            className="dl-panel dl-shelf dl-shelf-door tv-hoverable"
            onClick={() => onOpen(shelf.target)}
          >
            <span className="dl-shelf-head">
              <ArtIcon name={shelf.icon} size={30} />
              <h3>{shelf.title}</h3>
            </span>
            <p>{shelf.body}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

function DocumentsTab() {
  const t = useT();
  const [files, setFiles] = useState<CatalogFile[] | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fetch("/api/downloads/catalog", { signal });
      if (!res.ok) throw new Error("bad");
      const data = (await res.json()) as { files: CatalogFile[] };
      setFiles(data.files);
      setError(false);
    } catch {
      if (!signal?.aborted) setError(true);
    }
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load]);

  const visible = useMemo(() => {
    if (!files) return [];
    const q = query.trim().toLowerCase();
    if (!q) return files;
    return files.filter((f) => {
      const name = t(`downloads.file.${f.key}.name` as DictKey).toLowerCase();
      const desc = t(`downloads.file.${f.key}.desc` as DictKey).toLowerCase();
      return name.includes(q) || desc.includes(q) || f.filename.toLowerCase().includes(q);
    });
  }, [files, query, t]);

  /** The count moves server-side before the file serves; pull
   * the shelf again shortly after a click so the row the
   * visitor is looking at shows its new number. */
  function onDownloaded() {
    window.setTimeout(() => void load(), 900);
  }

  return (
    <div className="dl-documents">
      {/* New-download alerts (sweep E4): the opt-in box sits on
          the shelf itself, above the list it announces. It
          renders only for signed-in users (the component
          stands down for visitors — no dead controls). */}
      <ContentAlertToggle kind="downloads" />
      <section className="dl-panel">
        <p className="dl-step-note">{t("downloads.docs.sub")}</p>
        <SearchBar
          value={query}
          onChange={setQuery}
          placeholder={t("downloads.docs.searchPlaceholder")}
          ariaLabel={t("downloads.docs.searchPlaceholder")}
        />
        {error && (
          <div className="dl-load-error">
            <Alert tone="danger">{t("downloads.docs.loadError")}</Alert>
            <Button variant="secondary" onClick={() => void load()}>
              {t("downloads.docs.retry")}
            </Button>
          </div>
        )}
        {!error && files === null && <Spinner label={t("downloads.docs.loading")} />}
        {files !== null && (
          <div className="dl-table-wrap">
            <table className="dl-table">
              <thead>
                <tr>
                  <th scope="col">{t("downloads.docs.col.name")}</th>
                  <th scope="col">{t("downloads.docs.col.about")}</th>
                  <th scope="col">{t("downloads.docs.col.format")}</th>
                  <th scope="col" className="dl-num">{t("downloads.docs.col.downloads")}</th>
                  <th scope="col">
                    <span className="dl-sr-only">{t("downloads.docs.download")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((f) => (
                  <tr key={f.key}>
                    <td className="dl-name-cell">
                      <FileTypeArt kind={f.format === "xlsx" ? "sheet" : "pdf"} height={34} />
                      <strong>{t(`downloads.file.${f.key}.name` as DictKey)}</strong>
                      {/* Phone-only second line (FIX4): the folded
                          columns' facts — shown only under 700px
                          (downloads.css). */}
                      <span className="dl-file-meta">
                        {t(`downloads.file.${f.key}.desc` as DictKey)} ·{" "}
                        {t(f.format === "xlsx" ? "downloads.docs.format.xlsx" : "downloads.docs.format.pdf")}{" "}
                        · {f.download_count.toLocaleString()} {t("downloads.docs.col.downloads")}
                      </span>
                    </td>
                    <td className="dl-desc-cell">{t(`downloads.file.${f.key}.desc` as DictKey)}</td>
                    <td className="dl-format-cell">
                      {t(f.format === "xlsx" ? "downloads.docs.format.xlsx" : "downloads.docs.format.pdf")}
                    </td>
                    <td className="dl-num dl-count-cell">{f.download_count.toLocaleString()}</td>
                    <td className="dl-get-cell">
                      {f.key === "inspection-checklist" ? (
                        /* The one row whose action is Customize, not
                           Download (owner order 2026-11-09): the
                           wizard builds the visitor's own checklist
                           and the download happens inside it. */
                        <button
                          type="button"
                          className="dl-download-btn dl-customize-btn"
                          onClick={() => setWizardOpen(true)}
                        >
                          {t("downloads.docs.customize")}
                        </button>
                      ) : (
                        <a
                          className="dl-download-btn"
                          href={`/api/downloads/files/${f.key}`}
                          onClick={onDownloaded}
                        >
                          {t("downloads.docs.download")}
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={5} className="dl-empty-cell">
                      {t("downloads.docs.empty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <InspectionWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onDownloaded={onDownloaded}
      />
      <DownloadsConverter />
    </div>
  );
}

interface WallpaperSize {
  size: string;
  width: number;
  height: number;
  download_count: number;
}

interface Wallpaper {
  key: string;
  branded: boolean;
  category: string;
  download_count: number;
  sizes: WallpaperSize[];
}

/** The wallpaper categories (Sweep E2): exactly one per
 * piece, assigned in the backend catalog; the labels are
 * dictionary copy (downloads.wall.category.*). */
const WALLPAPER_CATEGORIES = [
  "cars",
  "tools",
  "engines",
  "abstract",
  "high-tech",
] as const;

/** An uncounted look at a piece (thumbnail or preview) — only
 * the Download buttons move a counter, through the same
 * /files/{key} path the documents use. */
function wallpaperViewUrl(key: string, size: string) {
  return `/api/downloads/wallpapers/${key}/view/${size}`;
}

/** The Wallpaper tab (Downloads Part 3): a gallery of uniform
 * tiles — the art, its name, its total download count — over
 * the shelf the API serves. A click opens the preview at
 * proper size with the three device downloads; each size
 * shows its own dimensions and its own count, and picking a
 * size previews that size's actual crop. */
function WallpapersTab() {
  const t = useT();
  const [wallpapers, setWallpapers] = useState<Wallpaper[] | null>(null);
  const [error, setError] = useState(false);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [previewSize, setPreviewSize] = useState("desktop");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("featured");

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fetch("/api/downloads/wallpapers", { signal });
      if (!res.ok) throw new Error("bad");
      const data = (await res.json()) as { wallpapers: Wallpaper[] };
      setWallpapers(data.wallpapers);
      setError(false);
    } catch {
      if (!signal?.aborted) setError(true);
    }
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load]);

  /* The header's search / category / sort (Sweep E2): the
   * prints browse toolbar's seats and treatment, run over
   * the shelf this tab already holds — search matches the
   * piece's name or description, the dropdown keeps exactly
   * one category, and the sorts mirror prints' where they
   * apply (prints' rating has no wallpaper counterpart; the
   * default seat is the shelf's own order). */
  const visible = useMemo(() => {
    if (!wallpapers) return [];
    const q = query.trim().toLowerCase();
    let list = wallpapers.filter((w) => {
      if (category && w.category !== category) return false;
      if (!q) return true;
      const name = t(`downloads.wallpaper.${w.key}.name` as DictKey).toLowerCase();
      const desc = t(`downloads.wallpaper.${w.key}.desc` as DictKey).toLowerCase();
      return name.includes(q) || desc.includes(q);
    });
    if (sort === "downloads") {
      list = [...list].sort((a, b) => b.download_count - a.download_count);
    } else if (sort === "name") {
      list = [...list].sort((a, b) =>
        t(`downloads.wallpaper.${a.key}.name` as DictKey).localeCompare(
          t(`downloads.wallpaper.${b.key}.name` as DictKey),
        ),
      );
    }
    return list;
  }, [wallpapers, query, category, sort, t]);

  const open = wallpapers?.find((w) => w.key === openKey) ?? null;

  function openPreview(w: Wallpaper) {
    setOpenKey(w.key);
    setPreviewSize("desktop");
  }

  /** Same rule as the Documents list: the count moves
   * server-side before the file serves; pull the shelf again
   * shortly after a click so the numbers on screen are live. */
  function onDownloaded() {
    window.setTimeout(() => void load(), 900);
  }

  return (
    <div className="dl-wallpapers">
      <section className="dl-panel">
        <p className="dl-step-note">{t("downloads.wall.sub")}</p>
        {/* The browse header (Sweep E2, owner's correction):
            the SAME seats and treatment as the 3D Print Files
            browse toolbar — search, Category dropdown, Sort
            dropdown — never a row of category buttons. */}
        <div className="dl-toolbar">
          <SearchBar
            value={query}
            onChange={setQuery}
            placeholder={t("downloads.wall.searchPlaceholder")}
            ariaLabel={t("downloads.wall.searchPlaceholder")}
          />
          <label className="dl-filter">
            <span>{t("downloads.wall.filter.category")}</span>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">{t("downloads.wall.filter.all")}</option>
              {WALLPAPER_CATEGORIES.map((key) => (
                <option key={key} value={key}>
                  {t(`downloads.wall.category.${key}` as DictKey)}
                </option>
              ))}
            </Select>
          </label>
          <label className="dl-filter">
            <span>{t("downloads.wall.sort.label")}</span>
            <Select value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="featured">{t("downloads.wall.sort.featured")}</option>
              <option value="downloads">{t("downloads.wall.sort.downloads")}</option>
              <option value="name">{t("downloads.wall.sort.name")}</option>
            </Select>
          </label>
        </div>
        {error && (
          <div className="dl-load-error">
            <Alert tone="danger">{t("downloads.docs.loadError")}</Alert>
            <Button variant="secondary" onClick={() => void load()}>
              {t("downloads.docs.retry")}
            </Button>
          </div>
        )}
        {!error && wallpapers === null && (
          <Spinner label={t("downloads.docs.loading")} />
        )}
        {wallpapers !== null && visible.length === 0 && (
          <p className="dl-wall-empty">{t("downloads.wall.empty")}</p>
        )}
        {wallpapers !== null && visible.length > 0 && (
          <div className="dl-wall-grid">
            {visible.map((w) => (
              <button
                key={w.key}
                type="button"
                className="dl-wall-tile tv-hoverable"
                onClick={() => openPreview(w)}
              >
                <img
                  src={wallpaperViewUrl(w.key, "thumb")}
                  alt=""
                  loading="lazy"
                />
                {w.branded && (
                  <span className="dl-wall-badge">
                    {t("downloads.wall.branded")}
                  </span>
                )}
                <span className="dl-wall-meta">
                  <span className="dl-wall-name">
                    {t(`downloads.wallpaper.${w.key}.name` as DictKey)}
                  </span>
                  <span className="dl-wall-count">
                    {w.download_count.toLocaleString()}{" "}
                    {t("downloads.docs.col.downloads")}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
      {open && (
        <Modal
          open
          onClose={() => setOpenKey(null)}
          title={t(`downloads.wallpaper.${open.key}.name` as DictKey)}
          size="lg"
          footer={
            <Button variant="secondary" onClick={() => setOpenKey(null)}>
              {t("downloads.wall.close")}
            </Button>
          }
        >
          <div className="dl-wall-preview">
            <img
              src={wallpaperViewUrl(open.key, previewSize)}
              alt={t(`downloads.wallpaper.${open.key}.name` as DictKey)}
            />
            <p className="dl-wall-desc">
              {t(`downloads.wallpaper.${open.key}.desc` as DictKey)}
            </p>
            <ul className="dl-wall-sizes">
              {open.sizes.map((s) => (
                <li
                  key={s.size}
                  className={
                    s.size === previewSize
                      ? "dl-wall-size is-active"
                      : "dl-wall-size"
                  }
                >
                  <button
                    type="button"
                    className="dl-wall-size-pick"
                    onClick={() => setPreviewSize(s.size)}
                    aria-pressed={s.size === previewSize}
                  >
                    <strong>
                      {t(`downloads.wall.size.${s.size}` as DictKey)}
                    </strong>
                    <span className="dl-wall-dims">
                      {s.width} × {s.height}
                    </span>
                    <span className="dl-wall-size-count">
                      {s.download_count.toLocaleString()}{" "}
                      {t("downloads.docs.col.downloads")}
                    </span>
                  </button>
                  <a
                    className="dl-download-btn"
                    href={`/api/downloads/files/${open.key}-${s.size}`}
                    onClick={onDownloaded}
                  >
                    {t("downloads.docs.download")}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default function DownloadsPage() {
  const t = useT();
  const { locale } = useLocale();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabId>(() => HASH_TO_TAB[window.location.hash] ?? "about");

  /* The visitor counter (owner order 2026-11-08): the teaser
   * page's quiet counter, mirrored for this page — one call on
   * load; the server decides whether THIS browser counts (its
   * own counted cookie, the teaser's rules; core/teaser.py) and
   * answers with this page's unique-visitor count. Since the
   * kit conversion (2026-11-10) the count renders as a fact in
   * the page header — the seat the owner confirmed the same
   * day when he found it there. Until a real number arrives
   * the fact is simply absent, and a failed call changes
   * nothing either: the counter is a quiet detail, never a
   * broken "0" and never a blocker. */
  const [visitors, setVisitors] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetch("/api/downloads/visit", { method: "POST" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("bad"))))
      .then((data: { count: number }) => {
        if (live) setVisitors(data.count);
      })
      .catch(() => {
        /* decoration only — silence is the failure state */
      });
    return () => {
      live = false;
    };
  }, []);

  /* The header's shelf counts (kit conversion, 2026-11-10):
   * the facts state how much is actually up, read from the
   * same public shelves the tabs serve — the document catalog,
   * the print shelf's browse total, the wallpaper shelf. Each
   * read is independent and best-effort, like the counter: a
   * failed read omits its fact, never blocks the page, and
   * never shows a placeholder number. */
  const [counts, setCounts] = useState<{
    documents: number | null;
    prints: number | null;
    wallpapers: number | null;
  }>({ documents: null, prints: null, wallpapers: null });
  useEffect(() => {
    const ctl = new AbortController();
    const { signal } = ctl;
    fetch("/api/downloads/catalog", { signal })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("bad"))))
      .then((data: { files: unknown[] }) =>
        setCounts((c) => ({ ...c, documents: data.files.length })),
      )
      .catch(() => {
        /* fact omitted — see the note above */
      });
    fetch("/api/prints/files?limit=1", { signal })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("bad"))))
      .then((data: { total: number }) =>
        setCounts((c) => ({ ...c, prints: data.total })),
      )
      .catch(() => {
        /* fact omitted — see the note above */
      });
    fetch("/api/downloads/wallpapers", { signal })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("bad"))))
      .then((data: { wallpapers: unknown[] }) =>
        setCounts((c) => ({ ...c, wallpapers: data.wallpapers.length })),
      )
      .catch(() => {
        /* fact omitted — see the note above */
      });
    return () => ctl.abort();
  }, []);

  // A landed /downloads#prints link follows the door to the
  // shelf's own page (the deep link names the tab; the tab is
  // a navigation, like Help's #videos).
  useEffect(() => {
    if (window.location.hash === "#prints") {
      navigate(PRINTS_PATH, { replace: true });
    }
  }, [navigate]);

  useEffect(() => {
    function onHash() {
      const next = HASH_TO_TAB[window.location.hash];
      if (next) setTab(next);
    }
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function pickTab(id: string) {
    if (id === "prints") {
      navigate(PRINTS_PATH);
      return;
    }
    const next = (id as TabId) ?? "about";
    setTab(next);
    window.history.replaceState(null, "", `#${next}`);
  }

  const fmt = new Intl.NumberFormat(locale);
  const facts: SectionPageFact[] = [];
  if (counts.documents !== null)
    facts.push({ label: t("downloads.tab.documents"), value: fmt.format(counts.documents) });
  if (counts.prints !== null)
    facts.push({ label: t("downloads.tab.prints"), value: fmt.format(counts.prints) });
  if (counts.wallpapers !== null)
    facts.push({ label: t("downloads.tab.wallpapers"), value: fmt.format(counts.wallpapers) });
  if (visitors !== null)
    facts.push({ label: t("downloads.fact.visitors"), value: fmt.format(visitors) });
  const tabs: TabItem[] = [
    { id: "about", label: t("downloads.tab.about"), content: <AboutTab onOpen={pickTab} /> },
    { id: "documents", label: t("downloads.tab.documents"), content: <DocumentsTab /> },
    { id: "prints", label: t("downloads.tab.prints"), content: null },
    { id: "wallpapers", label: t("downloads.tab.wallpapers"), content: <WallpapersTab /> },
  ];

  return (
    <div className="dl-page">
      {/* The kit header (conversion, 2026-11-10): the SAME
          SectionPageHeader every main-tab page renders — the
          downloads art plate, the title, the standing tagline,
          and the shelf facts. No Actions menu, per the note at
          the top of this file: the kit renders the Actions cell
          only when a page passes one, and this page has no
          commands or settings to pass. The page wears no
          masthead of its own (owner, 2026-11-10): the shell's
          header is the page's masthead, like every other
          page's. */}
      <SectionPageHeader
        thumb={<ArtIcon name="downloads" size={96} />}
        title={t("downloads.title")}
        subtitle={t("downloads.tagline")}
        facts={facts}
      />

      <Tabs tabs={tabs} activeId={tab} onChange={pickTab} />

      {/* No page footer of its own (footer unification, owner
          2026-11-07): the shell closes this page with the same
          shared site footer as the rest of the website. */}
    </div>
  );
}
