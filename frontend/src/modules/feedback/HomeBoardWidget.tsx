/** Home board widgets (boards lane, owner 2026-11-06 22:58):
 *  one widget per board — Bug Reports and Feature Requests —
 *  registered as Home blocks in CorePage with
 *  defaultVisible=false: OFF by default, offered in Home's
 *  Edit view (and Settings' page customization) to anyone who
 *  wants them, and a stored layout entry wins in both
 *  directions. Gated on the feedback module — the same module
 *  that gates the boards themselves.
 *
 *  Each shows the board's recent posts (newest first, the
 *  board's own default order): the title, the filer's
 *  urgency pill, and the upvote count; every row is the door
 *  to the post itself, and the footer's button opens the
 *  board. In Home Edit view the rows and the button go inert
 *  — a box never navigates while it's being arranged (the
 *  standing Home rule). Styles live in feedback.css.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { LinkButton, Panel } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { getBoard } from "./api";
import type { FeedbackBoard, FeedbackPost } from "./types";
import { UrgencyPill } from "./urgency";
import "./feedback.css";

const ROW_CAP = 5;

export function HomeBoardWidget({
  board,
  editing = false,
}: {
  board: FeedbackBoard;
  editing?: boolean;
}) {
  const t = useT();
  const [posts, setPosts] = useState<FeedbackPost[] | null>(null);

  useEffect(() => {
    let live = true;
    getBoard(board, true)
      .then((rows) => {
        if (live) setPosts(rows);
      })
      .catch(() => {
        if (live) setPosts([]);
      });
    return () => {
      live = false;
    };
  }, [board]);

  const visible = (posts ?? [])
    .filter((p) => p.visibility === "visible" || p.visibility === "held")
    .slice(0, ROW_CAP);
  const boardPath = board === "bug" ? "/feedback/bugs" : "/feedback/features";

  const rowCells = (post: FeedbackPost) => (
    <>
      <span className="tv-board-widget-name">{post.title}</span>
      <span className="tv-board-widget-meta">
        <UrgencyPill urgency={post.urgency} />
        {post.closed && <span>{t("feedback.closed")}</span>}
        <span>▲ {post.vote_count}</span>
      </span>
    </>
  );

  return (
    <Panel className="tv-home-widget">
      <h3 className="tv-widget-title">
        {t(board === "bug" ? "home.widget.boardBugs" : "home.widget.boardFeatures")}
      </h3>
      {posts !== null &&
        (visible.length === 0 ? (
          <p className="tv-board-widget-empty">{t("home.widget.boardEmpty")}</p>
        ) : (
          <div className="tv-board-widget-rows">
            {visible.map((post) =>
              editing ? (
                <div key={post.id} className="tv-board-widget-row">
                  {rowCells(post)}
                </div>
              ) : (
                <Link
                  key={post.id}
                  to={`/feedback/post/${post.id}`}
                  className="tv-board-widget-row"
                >
                  {rowCells(post)}
                </Link>
              ),
            )}
          </div>
        ))}
      {!editing && (
        <div className="tv-board-widget-foot">
          <LinkButton to={boardPath} variant="secondary" size="sm">
            {t("home.widget.openBoard")}
          </LinkButton>
        </div>
      )}
    </Panel>
  );
}
