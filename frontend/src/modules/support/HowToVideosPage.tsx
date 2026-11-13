import { useEffect, useMemo, useRef, useState } from "react";

import {
  Alert,
  EmptyState,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core/auth/RequireAuth";
import { useMyModules } from "../core/MyModules";
import { listPublishedVideos, type HelpVideo } from "./api";
import { VideoRowBody } from "./VideoRows";
import "./videos.css";

type SectionId = HelpVideo["section"];

const SECTIONS: SectionId[] = ["website", "app"];

/**
 * How-to videos (owner, 2026-11-06): a MAIN TAB LAYOUT page —
 * the Help & Support videos tab promoted to its own home. The
 * data is the SAME operator-managed list behind Help's tab
 * (Admin Support stays the single manager; this page and the
 * Help tab are two doors onto one list, never two copies).
 *
 * Header: the shared section-page header kit
 * (SectionPageHeader, program Lane 0) — thumbnail tile, the
 * title, and the facts — how many
 * videos there are, split by side. Below it, one tab per side
 * (Website videos / App videos, Help's own section labels);
 * each tab is a true list of its videos in the shared row
 * anatomy (thumbnail left, name + description right — the
 * Home widget's rows). Clicking a row plays the video in the
 * embedded player at the top of the tab (the Help tab's own
 * youtube-nocookie embed).
 *
 * Deep links: /how-to-videos#website / #app land on that tab;
 * /how-to-videos#video=<id> (the Home widget's rows, the
 * standing teaser-click pattern) lands on that video's tab
 * with the video open in the player.
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
  const [pickedTab, setPickedTab] = useState<SectionId | null>(null);
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
  // the list lands, it picks its own tab and opens in the
  // player. An unknown id simply falls back to the first tab.
  const linked = useMemo(
    () =>
      hash.videoId && videos
        ? (videos.find((v) => v.id === hash.videoId) ?? null)
        : null,
    [hash.videoId, videos],
  );
  const activeTab: SectionId =
    pickedTab ?? linked?.section ?? hash.tab ?? "website";
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

  const tabs: TabItem[] = SECTIONS.map((id) => ({
    id,
    label: sectionLabel(id),
    content: (
      <SectionList
        rows={(videos ?? []).filter((v) => v.section === id)}
        selectedId={effectiveSelectedId}
        onSelect={(video) => setSelectedId(video.id)}
        emptyTitle={sectionLabel(id)}
      />
    ),
  }));

  return (
    <div className="tv-stack">
      <SectionPageHeader
        thumb={<ArtIcon name="videos" size={96} />}
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
        // tabs directly below the header — the tabs themselves
        // are the whole menu, as Ryan settled for Help & Support
        // (2026-11-06) and the sweep confirmed for this page.
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
        <Tabs
          tabs={tabs}
          activeId={activeTab}
          onChange={(id) => setPickedTab(id as SectionId)}
        />
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
