import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { LinkButton, Panel, QuietSkeleton } from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { listPublishedVideos, type HelpVideo } from "../support/api";
import { videoThumbUrl } from "../support/VideoRows";

/**
 * The Home how-to videos widget (owner, 2026-11-06): a
 * full-width block in the Home layout framework (the
 * Notifications block's shape — a special block, not a
 * HomeWidget module widget), gated on the support module
 * exactly like the data behind it (the Help page's videos
 * tab and the support-gated /api/support/videos read).
 *
 * REBUILT as a showcase (dashboard-flare lane, owner order
 * 2026-11-09): the videos ride a sideways-scrolling strip of
 * their real YouTube thumbnails — the visible few in the box,
 * the rest a scroll away — each tile landing on the landing
 * page with that video open (the page's own #video= seat).
 * There is deliberately NO whole-box cover link — the strip
 * must scroll and the button must work, so the box as a whole
 * navigates nowhere (the Notifications pattern).
 *
 * With no published videos yet the frame still stands: the
 * honest on-their-way line and the button, no fake content.
 * In Edit view the tiles and the button go inert — a box
 * never navigates while customizing.
 */
export function HowToVideosBlock({
  editing = false,
  bare = false,
}: {
  editing?: boolean;
  /** Custom-widget composition (Lane 2): sections only —
   *  no Panel, no head; the composite box carries its own. */
  bare?: boolean;
}) {
  const t = useT();
  const [videos, setVideos] = useState<HelpVideo[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    listPublishedVideos()
      .then((rows) => {
        if (live) setVideos(rows);
      })
      .catch(() => {
        if (live) {
          setVideos([]);
          setFailed(true);
        }
      });
    return () => {
      live = false;
    };
  }, []);

  const inner = (
    <>
      {failed ? (
        <p className="tv-muted">{t("home.widgetLoadFailed")}</p>
      ) : videos === null ? (
        <QuietSkeleton lines={3} />
      ) : (
        <>
          {videos.length > 0 ? (
            <>
              <div className="tv-widget-lines">
                <p className="tv-widget-line">
                  {videos.length === 1
                    ? t("videos.widgetOne")
                    : t("videos.widgetCount").replace(
                        "{count}",
                        String(videos.length),
                      )}
                </p>
              </div>
              <div className="tv-widget-strip tv-widget-strip--videos">
                {videos.map((video) => {
                  const body = (
                    <>
                      <span className="tv-widget-tile-thumb" aria-hidden="true">
                        <img
                          src={videoThumbUrl(video.youtube_id)}
                          alt=""
                          loading="lazy"
                        />
                      </span>
                      <span className="tv-widget-tile-title">{video.title}</span>
                    </>
                  );
                  return editing ? (
                    <div key={video.id} className="tv-widget-tile">
                      {body}
                    </div>
                  ) : (
                    <Link
                      key={video.id}
                      to={`/how-to-videos#video=${video.id}`}
                      className="tv-widget-tile"
                    >
                      {body}
                    </Link>
                  );
                })}
              </div>
            </>
          ) : (
            <p className="tv-muted">{t("videos.widgetEmpty")}</p>
          )}
          {!editing ? (
            <div className="tv-widget-actions">
              <LinkButton to="/how-to-videos" variant="primary" size="sm">
                {t("videos.viewAll")}
              </LinkButton>
            </div>
          ) : null}
        </>
      )}
    </>
  );
  if (bare) return inner;
  return (
    <Panel className="tv-home-widget">
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone="info" aria-hidden="true">
          <ArtIcon name="videos" size={24} />
        </span>
        <h3 className="tv-widget-title">{t("help.tab.videos")}</h3>
      </div>
      {inner}
    </Panel>
  );
}
