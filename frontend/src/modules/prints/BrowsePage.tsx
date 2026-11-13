/**
 * /3dprints — the 3D print files shelf (Downloads
 * Part 2, owner order 2026-11-08).
 *
 * A main tab layout page (kit conversion, 2026-11-10 — the
 * ten-page program's standard): the shared SectionPageHeader
 * kit (the module's parts artwork in the plate, the standing
 * title and sub, honest facts read from the shelf itself —
 * live listings, total print-file downloads, and this page's
 * own visitor count) and the one Actions dropdown, carrying
 * Upload for registered seats (the module has no settings of
 * its own, so no Settings entry). Below it the shared Steel
 * Tabs: Browse · My Files (registered only — their uploads
 * and their maker-profile links). The Browse tab keeps the
 * section's OWN search, category filter, and sort in its
 * body, and the shelf is a TRUE list — one file per row with
 * its preview, category, publisher, rating, version, download
 * count, and its Download button.
 *
 * The shelf is PUBLIC: signed-out visitors browse, search,
 * filter, open records, and download print files. The seats
 * that need a member (upload, My Files) show the sign-in
 * prompt instead.
 *
 * The page carries its OWN unique-visitor counter (owner
 * order 2026-11-10): POST /api/prints/visit, its own count,
 * separate from the teaser's and the Downloads page's,
 * displayed as a header fact — the seat the Downloads
 * counter rides in, by the owner's same-day word.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  Alert,
  Button,
  EmptyState,
  FormField,
  LinkButton,
  SearchBar,
  Select,
  Spinner,
  Tabs,
  TextInput,
  useToast,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import {
  SectionPageHeader,
  type SectionPageFact,
} from "../../components/SectionPageHeader";
import { useLocale, useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { useAuth } from "../core";
import { ContentAlertToggle } from "../core/contentAlerts";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import {
  browsePrints,
  createMyLink,
  deleteMyLink,
  getMyLinks,
  getMyPrints,
  printDownloadUrl,
  previewUrl,
} from "./api";
import { RemoveFileModal } from "./modals";
import { StarsDisplay } from "./Stars";
import { PRINT_CATEGORIES, type MakerLink, type PrintFileRow } from "./types";
import "./prints.css";

function categoryLabel(t: (k: DictKey) => string, key: string): string {
  return t(`prints.category.${key}` as DictKey);
}

function RatingCell({ row }: { row: PrintFileRow }) {
  const t = useT();
  if (row.rating.count === 0 || row.rating.average === null) {
    return <span className="pr-muted">{t("prints.noRatings")}</span>;
  }
  return (
    <span className="pr-rating-cell">
      <StarsDisplay average={row.rating.average} />
      <span>
        {row.rating.average.toFixed(1)} ({row.rating.count}{" "}
        {row.rating.count === 1 ? t("prints.ratingWord") : t("prints.ratingsWord")})
      </span>
    </span>
  );
}

function BrowsePanel() {
  const t = useT();
  const [files, setFiles] = useState<PrintFileRow[] | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("newest");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await browsePrints({
          q: query.trim(),
          category: category || undefined,
          sort,
        });
        if (signal?.aborted) return;
        setFiles(data.files);
        setError(false);
      } catch {
        if (!signal?.aborted) setError(true);
      }
    },
    [query, category, sort],
  );

  useEffect(() => {
    const ctl = new AbortController();
    const timer = window.setTimeout(() => void load(ctl.signal), 250);
    return () => {
      window.clearTimeout(timer);
      ctl.abort();
    };
  }, [load]);

  return (
    <section className="pr-panel">
      <div className="pr-toolbar">
        <SearchBar
          value={query}
          onChange={setQuery}
          placeholder={t("prints.search.placeholder")}
          ariaLabel={t("prints.search.placeholder")}
        />
        <label className="pr-filter">
          <span>{t("prints.filter.category")}</span>
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("prints.filter.all")}</option>
            {PRINT_CATEGORIES.map((key) => (
              <option key={key} value={key}>
                {categoryLabel(t, key)}
              </option>
            ))}
          </Select>
        </label>
        <label className="pr-filter">
          <span>{t("prints.sort.label")}</span>
          <Select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="newest">{t("prints.sort.newest")}</option>
            <option value="downloads">{t("prints.sort.downloads")}</option>
            <option value="rating">{t("prints.sort.rating")}</option>
          </Select>
        </label>
      </div>

      {error && (
        <div className="pr-load-error">
          <Alert tone="danger">{t("prints.loadError")}</Alert>
          <Button variant="secondary" onClick={() => void load()}>
            {t("prints.retry")}
          </Button>
        </div>
      )}
      {!error && files === null && <Spinner label={t("prints.loading")} />}
      {files !== null && (
        <div className="pr-table-wrap">
          <table className="pr-table pr-table--browse">
            <thead>
              <tr>
                <th scope="col">{t("prints.col.file")}</th>
                <th scope="col">{t("prints.col.category")}</th>
                <th scope="col">{t("prints.col.publisher")}</th>
                <th scope="col">{t("prints.col.rating")}</th>
                <th scope="col">{t("prints.col.version")}</th>
                <th scope="col" className="pr-num">{t("prints.col.downloads")}</th>
                <th scope="col">
                  <span className="pr-sr-only">{t("prints.download")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {files.map((row) => (
                <tr key={row.id}>
                  <td className="pr-file-cell">
                    <Link className="pr-thumb" to={`/3dprints/${row.id}`}>
                      {row.has_preview ? (
                        <img src={previewUrl(row.id)} alt="" />
                      ) : (
                        <ArtIcon name="parts" size={26} />
                      )}
                    </Link>
                    <Link className="pr-file-title" to={`/3dprints/${row.id}`}>
                      {row.title}
                    </Link>
                    {/* Phone-only second line (FIX4): the facts of
                        the columns the phone list folds away —
                        shown only under 640px (prints.css). */}
                    <span className="pr-file-meta">
                      {categoryLabel(t, row.category)} · v{row.current_version} ·{" "}
                      {row.download_count.toLocaleString()} {t("prints.col.downloads")}
                      {row.rating.count > 0 && row.rating.average !== null
                        ? ` · ${row.rating.average.toFixed(1)} (${row.rating.count})`
                        : ""}
                      {` · ${row.publisher.display_name}`}
                    </span>
                  </td>
                  <td>{categoryLabel(t, row.category)}</td>
                  <td>{row.publisher.display_name}</td>
                  <td>
                    <RatingCell row={row} />
                  </td>
                  <td>v{row.current_version}</td>
                  <td className="pr-num">{row.download_count.toLocaleString()}</td>
                  <td className="pr-get-cell">
                    <a className="pr-download-btn" href={printDownloadUrl(row.id)}>
                      {t("prints.download")}
                    </a>
                  </td>
                </tr>
              ))}
              {files.length === 0 && (
                <tr>
                  <td colSpan={7} className="pr-empty-cell">
                    {query || category ? t("prints.empty") : t("prints.emptyShelf")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MyFilesPanel() {
  const t = useT();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [files, setFiles] = useState<PrintFileRow[] | null>(null);
  const [links, setLinks] = useState<MakerLink[] | null>(null);
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [linkError, setLinkError] = useState("");
  const [removing, setRemoving] = useState<PrintFileRow | null>(null);

  const load = useCallback(async () => {
    try {
      const [f, l] = await Promise.all([getMyPrints(), getMyLinks()]);
      setFiles(f.files);
      setLinks(l.links);
    } catch {
      setFiles([]);
      setLinks([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function addLink() {
    setLinkError("");
    try {
      await createMyLink(label.trim(), url.trim());
      setLabel("");
      setUrl("");
      toast(t("prints.my.linkSaved"));
      await load();
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    }
  }

  async function dropLink(id: string) {
    try {
      await deleteMyLink(id);
      toast(t("prints.my.linkDeleted"));
      await load();
    } catch {
      /* the list reload shows the truth either way */
      await load();
    }
  }

  return (
    <div className="pr-my">
      <section className="pr-panel">
        <p className="pr-step-note">{t("prints.my.sub")}</p>
        {files === null ? (
          <Spinner label={t("prints.loading")} />
        ) : files.length === 0 ? (
          /* The shared nothing-here-yet kit (Sweep A1, finding
             07-F9): the old empty line was a dead end — the only
             Upload door sat hidden in the page Actions menu.
             Now the empty panel itself carries the door. */
          <EmptyState
            art="parts"
            title={t("prints.my.emptyTitle")}
            description={t("prints.my.empty")}
            action={
              <LinkButton to="/3dprints/upload">{t("prints.upload")}</LinkButton>
            }
          />
        ) : (
          <div className="pr-table-wrap">
            <table className="pr-table pr-table--my">
              <thead>
                <tr>
                  <th scope="col">{t("prints.col.file")}</th>
                  <th scope="col">{t("prints.col.category")}</th>
                  <th scope="col">{t("prints.col.version")}</th>
                  <th scope="col" className="pr-num">{t("prints.col.downloads")}</th>
                  <th scope="col">
                    <span className="pr-sr-only">{t("prints.actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {files.map((row) => (
                  <tr key={row.id} className={row.status !== "live" ? "pr-row-removed" : ""}>
                    <td className="pr-file-cell">
                      <span className="pr-thumb">
                        {row.has_preview ? (
                          <img src={previewUrl(row.id)} alt="" />
                        ) : (
                          <ArtIcon name="parts" size={26} />
                        )}
                      </span>
                      <span className="pr-file-title">{row.title}</span>
                      <span className="pr-file-meta">
                        {categoryLabel(t, row.category)} · v{row.current_version} ·{" "}
                        {row.download_count.toLocaleString()} {t("prints.col.downloads")}
                      </span>
                      {row.status !== "live" && (
                        <span className="pr-removed-chip">{t("prints.my.removed")}</span>
                      )}
                    </td>
                    <td>{categoryLabel(t, row.category)}</td>
                    <td>v{row.current_version}</td>
                    <td className="pr-num">{row.download_count.toLocaleString()}</td>
                    <td className="pr-my-actions">
                      {row.status === "live" && (
                        <>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => navigate(`/3dprints/${row.id}`)}
                          >
                            {t("prints.my.view")}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => navigate(`/3dprints/${row.id}/edit`)}
                          >
                            {t("prints.my.edit")}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => navigate(`/3dprints/upload?update=${row.id}`)}
                          >
                            {t("prints.my.update")}
                          </Button>
                          <button
                            type="button"
                            className="tv-list-remove-btn"
                            aria-label={`${t("prints.my.remove")}: ${row.title}`}
                            title={t("prints.my.remove")}
                            onClick={() => setRemoving(row)}
                          >
                            {"−"}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="pr-panel">
        <h2 className="pr-panel-title">{t("prints.my.linksTitle")}</h2>
        <p className="pr-step-note">{t("prints.my.linksSub")}</p>
        {links === null ? (
          <Spinner label={t("prints.loading")} />
        ) : links.length === 0 ? (
          <p className="pr-muted">{t("prints.my.noLinks")}</p>
        ) : (
          <ul className="pr-links-list">
            {links.map((link) => (
              <li key={link.id} className="pr-link-row">
                <a
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="pr-link-label pr-link-url"
                  title={link.url}
                >
                  {link.label || link.url}
                </a>
                <Button variant="secondary" size="sm" onClick={() => void dropLink(link.id)}>
                  {t("prints.my.deleteLink")}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="pr-link-form">
          <FormField label={t("prints.my.linkLabel")}>
            <TextInput value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} />
          </FormField>
          <FormField label={t("prints.my.linkUrl")}>
            <TextInput
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              maxLength={500}
              placeholder="https://makerworld.com/@you"
            />
          </FormField>
          <Button onClick={() => void addLink()} disabled={!label.trim() || !url.trim()}>
            {t("prints.my.addLink")}
          </Button>
        </div>
        {linkError && <Alert tone="danger">{linkError}</Alert>}
      </section>

      {removing && (
        <RemoveFileModal
          open
          fileId={removing.id}
          onClose={() => setRemoving(null)}
          onRemoved={() => {
            setRemoving(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

export default function PrintsBrowsePage() {
  const t = useT();
  const { locale } = useLocale();
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  /* The visitor counter (owner order 2026-11-10): this page's
   * OWN quiet counter, the teaser/Downloads pattern — one call
   * on load; the server decides whether THIS browser counts
   * (its own counted cookie, the shared rules; core/teaser.py)
   * and answers with this page's unique-visitor count. Since
   * the kit conversion (2026-11-10) the count renders as a
   * fact in the page header — the seat the owner accepted for
   * the Downloads counter the same day; consistency wins.
   * Until a real number arrives the fact is simply absent,
   * and a failed call changes nothing either: a quiet detail,
   * never a broken "0" and never a blocker. The counter lives
   * on THIS page only — the Downloads page's 3D Print Files
   * tab is a door to here, not a second seat. */
  const [visitors, setVisitors] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetch("/api/prints/visit", { method: "POST" })
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
  /* The header's shelf facts (kit conversion, 2026-11-10):
   * the browse endpoint's shelf-wide stats — live listings
   * and their total print-file downloads, computed server-
   * side over the whole shelf, never narrowed by the Browse
   * tab's own search/filter. One unfiltered call on load;
   * until it lands the facts are simply absent. */
  const [stats, setStats] = useState<{ listings: number; downloads: number } | null>(
    null,
  );
  useEffect(() => {
    let live = true;
    browsePrints({})
      .then((data) => {
        if (live) setStats(data.stats);
      })
      .catch(() => {
        /* facts are decoration — absence is the failure state */
      });
    return () => {
      live = false;
    };
  }, []);

  // The Home widget's My Uploads door deep-links here with
  // #my (dashboard-flare lane, 2026-11-09): the hash picks the
  // tab on arrival and whenever it changes, the Reports page's
  // own hash-to-tab pattern.
  const [tab, setTab] = useState(() =>
    location.hash === "#my" ? "my" : "browse",
  );

  useEffect(() => {
    if (location.hash === "#my") setTab("my");
  }, [location.hash]);

  const fmt = new Intl.NumberFormat(locale);
  const facts: SectionPageFact[] = [];
  if (stats !== null) {
    facts.push({ label: t("prints.fact.listings"), value: fmt.format(stats.listings) });
    facts.push({ label: t("prints.col.downloads"), value: fmt.format(stats.downloads) });
  }
  if (visitors !== null)
    facts.push({ label: t("prints.fact.visitors"), value: fmt.format(visitors) });

  const tabs: TabItem[] = useMemo(() => {
    const list: TabItem[] = [
      { id: "browse", label: t("prints.tab.browse"), content: <BrowsePanel /> },
    ];
    if (user) {
      list.push({ id: "my", label: t("prints.tab.my"), content: <MyFilesPanel /> });
    }
    return list;
  }, [t, user]);

  return (
    <div className="pr-page">
      {/* The page header is the shared SectionPageHeader kit
          (main tab layout conversion, 2026-11-10): the module's
          parts artwork in the plate, the standing title and
          sub, honest facts from the shelf itself, and the one
          Actions dropdown — Upload for registered seats. The
          prints module has NO settings of its own (checked:
          no prints section in the settings registry), so the
          menu carries no Settings entry. Signed-out visitors
          get no menu: their upload door is the standing
          sign-in note in the same seat, exactly as the door
          audit established. */}
      <SectionPageHeader
        thumb={<ArtIcon name="parts" size={96} />}
        title={t("prints.title")}
        subtitle={t("prints.sub")}
        facts={facts}
        actions={
          user ? (
            <SettingsActionsMenu
              ariaLabel={t("prints.title")}
              buttonLabel={t("inventory.actions")}
              entries={[
                {
                  key: "upload",
                  label: t("prints.upload"),
                  run: () => navigate("/3dprints/upload"),
                },
              ]}
            />
          ) : (
            <p className="pr-signin-note">
              <Link to="/login">{t("prints.signIn")}</Link> {t("prints.signInRest")}
            </p>
          )
        }
      />
      {/* New print file alerts (sweep E4): the opt-in box sits
          on the shelf itself, under the header. Signed-in
          users only — the component stands down for visitors. */}
      <ContentAlertToggle kind="prints" />
      <Tabs tabs={tabs} activeId={tab} onChange={setTab} />
    </div>
  );
}
