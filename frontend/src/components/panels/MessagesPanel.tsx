import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useAuth } from "../../modules/core/AuthContext";
import { getUnread } from "../../modules/messaging/api";
import type { UnreadSummary } from "../../modules/messaging/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Messages panel (Rail Steel conversion, Phase 2c).
 *
 * The page's folders (Inbox / Requests / Blocked) are local tab
 * state — no URL carries a folder — so the panel links the page
 * once and carries the counts from the module's own summary
 * call, GET /messaging/unread (inbox_unread / requests_count).
 * The Moderation link mirrors the page's own gate exactly
 * (MessagesPage: operator, or role moderator / community_admin);
 * the queue page and the API re-check the same ladder.
 */
export function MessagesPanel() {
  const { user } = useAuth();
  const [unread, setUnread] = useState<UnreadSummary | null>(null);
  const isMod = Boolean(
    user?.is_operator ||
      user?.role === "moderator" ||
      user?.role === "community_admin",
  );

  useEffect(() => {
    let live = true;
    getUnread()
      .then((u) => {
        if (live) setUnread(u);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <p className="tv-sp-kicker">Messages</p>
      <h2 className="tv-sp-title">Messages</h2>
      <PanelUtility />
      <p className="tv-sp-group">Folders</p>
      <div className="tv-sp-list">
        <NavLink
          to="/messages"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Inbox &amp; requests</span>
          {unread && unread.inbox_unread > 0 && (
            <span className="tv-sp-count">
              {unread.inbox_unread.toLocaleString("en-US")}
            </span>
          )}
        </NavLink>
        {isMod && (
          <NavLink
            to="/moderation"
            className={({ isActive }) =>
              `tv-sp-item${isActive ? " is-active" : ""}`
            }
          >
            <span>Moderation queue</span>
          </NavLink>
        )}
      </div>
      {unread && (
        <ul className="tv-sp-stats">
          <li>
            <span>Unread in inbox</span>
            <strong>{unread.inbox_unread.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Requests waiting</span>
            <strong>{unread.requests_count.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {unread && unread.requests_count > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Message requests</p>
          <p>
            {unread.requests_count} first contact
            {unread.requests_count === 1 ? " is" : "s are"} waiting in
            Requests — links stay inert there until you accept.
          </p>
        </div>
      )}
    </>
  );
}
