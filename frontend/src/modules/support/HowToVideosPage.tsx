import { useEffect, useMemo, useRef, useState } from "react";

import {
  Alert,
  EmptyState,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  Toggle,
  type TabItem,
} from "../../components";
import { HeaderArt } from "../../components/HeaderArt";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core/auth/RequireAuth";
import { useMyModules } from "../core/MyModules";
import {
  listPublishedVideos,
  VIDEO_CATEGORIES,
  type HelpVideo,
  type HelpVideoCategory,
} from "./api";
import { VideoRowBody } from "./VideoRows";
import "./videos.css";

type SectionId = HelpVideo["section"];
type CategoryTabId = "all" | HelpVideoCategory;

/**
 * How-to videos (owner, 2026-11-06; restructured 2026-11-14):
 * a MAIN TAB LAYOUT page — the Help & Support videos tab
 * promoted to its own home. The data is the SAME
 * operator-managed list behind Help's tab (Admin Support stays
 * the single manager; this page and the Help tab are two doors
 * onto one list, never two copies).
 *
 * Header: the shared section-page header kit
 * (SectionPageHeader) — thumbnail tile, the title, and the
 * facts — how many videos there are, split by side. Below it,
 * the side picker is a TOGGLE SWITCH (owner, 2026-11-14): one
 * side of the switch is "Website Videos", the other "App
 * videos" — the settled shared switch, its two labels written
 * out beside it, and either label clickable too. Below the
 * switch, the CATEGORY TABS: ALL first, then one tab per
 * category the chosen side's videos actually use (Inventory,
 * Records, Dealers, Claims, … — the category set in Admin when
 * the video is added). Each tab is a true list of its videos
 * in the shared row anatomy (thumbnail left, name +
 * description right — the Home widget's rows). Clicking a row
 * plays the video in the embedded player at the top of the
 * tab (the Help tab's own youtube-nocookie embed).
 *
 * Deep links: /how-to-videos#website / #app land on that side;
 * /how-to-videos#video=<id> (the Home widget's rows, the
 * standing teaser-click pattern) lands on that video's side
 * and category with the video open in the player.
 *
 * The page rides the support module like its data: the list
 * endpoint is support-gated server-side, and with the module
 * off the page says so plainly instead of failing.
 */
function parseHash(): { tab?: SectionId; videoId?: string } {
  const raw = window.location.hash.replace(/^#/, "");
  if (raw.startsWith("video=")) {
    return { videoId: decodeURIComponent(raw.slice("video=".length)) };
  }
  if (raw === "website" || raw === "app") return { tab: raw };
  return {};
}

function SectionList({
  rows,
  selectedId,
  onSelect,
  emptyTitle,
}: {
  rows: HelpVideo[];
  selectedId: string | null;
  onSelect: (video: HelpVideo) => void;
  emptyTitle: string;
}) {
  const t = useT();
  const playerRef = useRef<HTMLDivElement | null>(null);
  const selected = rows.find((v) => v.id === selectedId) ?? null;

  // A fresh pick (a row click, or the widget's deep link)
  // brings the player into view — the list can be long.
  useEffect(() => {
    if (selected) {
      playerRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [selected]);

  if (rows.length === 0) {
    // The honest empty state — Help's own approved wording:
    // the area exists, the videos are on their way.
    return (
      <EmptyState title={emptyTitle} description={t("help.videos.empty")} />
    );
  }
  return (
    <div>
      {selected ? (
        <div className="tv-video-player" ref={playerRef}>
          <div className="tv-video-player-frame">
            <iframe
              src={`https://www.youtube-nocookie.com/embed/${selected.youtube_id}`}
              title={selected.title}
              loading="lazy"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
          <h2 className="tv-video-player-title">{selected.title}</h2>
          {selected.summary ? (
            <p className="tv-video-player-desc">{selected.summary}</p>
          ) : null}
        </div>
      ) : null}
      <div className="tv-video-list">
        {rows.map((video) => (
          <button
            key={video.id}
            type="button"
            className="tv-video-row"
            data-selected={video.id === selectedId || undefined}
            aria-current={video.id === selectedId || undefined}
            onClick={() => onSelect(video)}
          >
            <VideoRowBody video={video} />
          </button>
        ))}
      </div>
    </div>
  );
}

function VideosHome() {
  const t = useT();
  const myModules = useMyModules();
  const supportOn = myModules.has("support");
  const modulesKnown = !myModules.loading && myModules.modules !== null;

  const [videos, setVideos] = useState<HelpVideo[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [pickedSection, setPickedSection] = useState<SectionId | null>(null);
  const [pickedCategory, setPickedCategory] =
    useState<CategoryTabId | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hash] = useState(parseHash);

  useEffect(() => {
    if (!supportOn) return;
    let cancelled = false;
    listPublishedVideos()
      .then((rows) => {
        if (!cancelled) setVideos(rows);
      })
      .catch(() => {
        if (!cancelled) {
          setVideos([]);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [supportOn]);

  // The deep-linked video (the Home widget's row click): once
  // the list lands, it picks its own side and category and
  // opens in the player. An unknown id simply falls back to
  // the first side, ALL tab.
  const linked = useMemo(
    () =>
      hash.videoId && videos
        ? (videos.find((v) => v.id === hash.videoId) ?? null)
        : null,
    [hash.videoId, videos],
  );
  const section: SectionId =
    pickedSection ?? linked?.section ?? hash.tab ?? "website";
  const effectiveSelectedId = selectedId ?? linked?.id ?? null;

  const counts = useMemo(() => {
    const list = videos ?? [];
    return {
      total: list.length,
      website: list.filter((v) => v.section === "website").length,
      app: list.filter((v) => v.section === "app").length,
    };
  }, [videos]);

  const sectionLabel = (id: SectionId): string =>
    id === "website" ? t("help.videos.website") : t("help.videos.app");

  // Flipping the switch starts the other side fresh: ALL tab,
  // nothing playing — the two sides are separate lists.
  const pickSection = (next: SectionId) => {
    setPickedSection(next);
    setPickedCategory("all");
    setSelectedId(null);
  };

  const sideRows = (videos ?? []).filter((v) => v.section === section);
  // One tab per category this side's videos actually use, in
  // catalog order; ALL always leads.
  const presentCategories = VIDEO_CATEGORIES.filter((key) =>
    sideRows.some((v) => v.category === key),
  );
  const category: CategoryTabId =
    pickedCategory !== null &&
    (pickedCategory === "all" || presentCategories.includes(pickedCategory))
      ? pickedCategory
      : linked && linked.section === section
        ? linked.category
        : "all";

  const tabs: TabItem[] = [
    {
      id: "all",
      label: t("videos.cat.all"),
      content: (
        <SectionList
          rows={sideRows}
          selectedId={effectiveSelectedId}
          onSelect={(video) => setSelectedId(video.id)}
          emptyTitle={sectionLabel(section)}
        />
      ),
    },
    ...presentCategories.map((key) => ({
      id: key,
      label: t(`videos.cat.${key}`),
      content: (
        <SectionList
          rows={sideRows.filter((v) => v.category === key)}
          selectedId={effectiveSelectedId}
          onSelect={(video: HelpVideo) => setSelectedId(video.id)}
          emptyTitle={t(`videos.cat.${key}`)}
        />
      ),
    })),
  ];

  return (
    <div className="tv-stack">
      <SectionPageHeader
        thumb={<HeaderArt name="videos" />}
        title={t("help.tab.videos")}
        subtitle={t("videos.subtitle")}
        facts={
          videos !== null && !failed
            ? [
                { label: t("help.tab.videos"), value: counts.total },
                { label: t("help.videos.website"), value: counts.website },
                { label: t("help.videos.app"), value: counts.app },
              ]
            : undefined
        }
        // NO Actions menu (sweep B8, 2026-11-12, sweep finding
        // 08-F4): its only entries were jumps to the two section
        // tabs directly below the header — the switch and tabs
        // themselves are the whole menu, as Ryan settled for
        // Help & Support (2026-11-06).
      />

      {!supportOn ? (
        modulesKnown ? (
          <Panel>
            <EmptyState
              title={t("help.tab.videos")}
              description={t("videos.moduleOff")}
            />
          </Panel>
        ) : (
          <Spinner />
        )
      ) : videos === null ? (
        <Spinner />
      ) : failed ? (
        <Alert tone="danger">{t("help.videos.loadError")}</Alert>
      ) : (
        <>
          <div className="tv-videos-switchrow">
            <button
              type="button"
              className="tv-videos-side"
              data-active={section === "website" || undefined}
              onClick={() => pickSection("website")}
            >
              {t("help.videos.website")}
            </button>
            <Toggle
              checked={section === "app"}
              onChange={(on) => pickSection(on ? "app" : "website")}
              ariaLabel={`${t("help.videos.website")} / ${t("help.videos.app")}`}
            />
            <button
              type="button"
              className="tv-videos-side"
              data-active={section === "app" || undefined}
              onClick={() => pickSection("app")}
            >
              {t("help.videos.app")}
            </button>
          </div>
          <Tabs
            tabs={tabs}
            activeId={category}
            onChange={(id) => setPickedCategory(id as CategoryTabId)}
          />
        </>
      )}
    </div>
  );
}

export default function HowToVideosPage() {
  return (
    <RequireAuth>
      <VideosHome />
    </RequireAuth>
  );
}
