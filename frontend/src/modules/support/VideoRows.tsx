import { Link } from "react-router-dom";

import type { HelpVideo } from "./api";
import "./videos.css";

/**
 * The how-to video row (owner, 2026-11-06): ONE anatomy in
 * both seats — the Home widget and the /how-to-videos landing
 * page. The video's thumbnail fills the left column; its name
 * and description fill the right. The row itself is the click
 * target and wears the site-wide hover system's ROWS
 * treatment (the Main highlight effect — .tv-video-row is
 * registered in railsteel-panels.css).
 *
 * Thumbnails are YouTube's own image service for the video id
 * (the same id the Help tab embeds) — no video files or
 * thumbnail images are hosted here.
 */
export function videoThumbUrl(youtubeId: string): string {
  return `https://i.ytimg.com/vi/${youtubeId}/mqdefault.jpg`;
}

export function VideoRowBody({ video }: { video: HelpVideo }) {
  return (
    <>
      <span className="tv-video-thumb" aria-hidden="true">
        <img src={videoThumbUrl(video.youtube_id)} alt="" loading="lazy" />
        <span className="tv-video-play" />
      </span>
      <span className="tv-video-main">
        <span className="tv-video-name">{video.title}</span>
        {video.summary ? (
          <span className="tv-video-desc">{video.summary}</span>
        ) : null}
      </span>
    </>
  );
}

/**
 * The Home widget's list (owner, 2026-11-06): exactly three
 * rows tall — everything past the third row scrolls inside
 * the widget (the Notifications capped pattern). A row click
 * lands on the videos page with that video open. In Home's
 * Edit view the rows render inert: a box never navigates
 * while customizing.
 */
export function WidgetVideoList({
  videos,
  editing = false,
}: {
  videos: HelpVideo[];
  editing?: boolean;
}) {
  const capped = videos.length > 3;
  return (
    <div
      className={`tv-video-list${capped ? " tv-video-list--capped" : ""}`}
    >
      {videos.map((video) =>
        editing ? (
          <div key={video.id} className="tv-video-row">
            <VideoRowBody video={video} />
          </div>
        ) : (
          <Link
            key={video.id}
            className="tv-video-row"
            to={`/how-to-videos#video=${video.id}`}
          >
            <VideoRowBody video={video} />
          </Link>
        ),
      )}
    </div>
  );
}
