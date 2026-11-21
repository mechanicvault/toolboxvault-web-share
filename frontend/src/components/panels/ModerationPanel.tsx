import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useAuth } from "../../modules/core/AuthContext";
import { useMyModules } from "../../modules/core/MyModules";
import { getFeedbackHeld, getFeedbackReports } from "../../modules/feedback/api";
import { getForumHeld, getForumReports } from "../../modules/forum/api";
import { listRatingReports } from "../../modules/marketplace/api";
import { listHeld, listReports } from "../../modules/messaging/api";
import { PanelUtility } from "./PanelUtility";

/**
 * The Moderation panel (Rail Steel conversion, Phase 2c) for
 * /moderation.
 *
 * Gating mirrors ModerationPage exactly: operator, or role
 * moderator / community_admin. Anyone else gets the same
 * "Moderators only" posture the page itself renders — no counts
 * are fetched for them (the mod endpoints would 403 anyway).
 *
 * For moderators the stats are the queue's own reads — the same
 * Promise.all ModerationPage makes (message reports open,
 * messages held, forum reports open, forum posts held, rating
 * reports open, feedback reports open, feedback held), except
 * the messaging and marketplace reads are only made while their
 * module is effective for the viewer (parked-module signs,
 * 2026-10-31). Each read is caught separately here so one
 * failing queue hides its own row instead of blanking the panel.
 */
export function ModerationPanel() {
  const { user } = useAuth();
  const allowed = Boolean(
    user?.is_operator ||
      user?.role === "moderator" ||
      user?.role === "community_admin",
  );
  const { loading: modulesLoading, has } = useMyModules();
  // Parked-module signs (owner directive, 2026-10-31): the
  // messaging queues and the Messages link render only while
  // messaging is effective for this moderator, and the rating
  // queue only while marketplace is — each returns on its own
  // when its module is unparked. (The queue reads ride the role
  // ladder, not the module switch, so without this gate the rows
  // would keep answering — and showing — while parked.)
  const messagingOn = !modulesLoading && has("messaging");
  const marketplaceOn = !modulesLoading && has("marketplace");
  const [rows, setRows] = useState<{ label: string; count: number }[] | null>(
    null,
  );

  useEffect(() => {
    if (!allowed) return;
    let live = true;
    const jobs: [string, Promise<unknown[]>][] = [];
    if (messagingOn) {
      jobs.push(["Message reports", listReports("open")]);
      jobs.push(["Messages held", listHeld()]);
    }
    jobs.push(["Forum reports", getForumReports("open")]);
    jobs.push(["Forum posts held", getForumHeld()]);
    if (marketplaceOn) {
      jobs.push(["Rating reports", listRatingReports("open")]);
    }
    jobs.push(["Feedback reports", getFeedbackReports("open")]);
    jobs.push(["Feedback held", getFeedbackHeld()]);
    void Promise.all(
      jobs.map(([label, job]) =>
        job
          .then((list) => ({ label, count: list.length }))
          .catch(() => null),
      ),
    ).then((results) => {
      if (!live) return;
      setRows(
        results.filter(
          (r): r is { label: string; count: number } => r !== null,
        ),
      );
    });
    return () => {
      live = false;
    };
  }, [allowed, messagingOn, marketplaceOn]);

  const total = rows?.reduce((acc, r) => acc + r.count, 0) ?? 0;

  return (
    <>
      <p className="tv-sp-kicker">Moderation</p>
      <h2 className="tv-sp-title">Moderation</h2>
      <PanelUtility />
      {!allowed ? (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Moderators only</p>
          <p>
            The moderation queue is for community moderators and
            operators. To report harassment, open the conversation and
            use Report — it lands here for review.
          </p>
        </div>
      ) : (
        <>
          <p className="tv-sp-group">Queue</p>
          <div className="tv-sp-list">
            <NavLink
              to="/moderation"
              end
              className={({ isActive }) =>
                `tv-sp-item${isActive ? " is-active" : ""}`
              }
            >
              <span>Moderation queue</span>
              {rows !== null && total > 0 && (
                <span className="tv-sp-count">{total.toLocaleString("en-US")}</span>
              )}
            </NavLink>
            {messagingOn && (
              <NavLink
                to="/messages"
                className={({ isActive }) =>
                  `tv-sp-item${isActive ? " is-active" : ""}`
                }
              >
                <span>Messages</span>
              </NavLink>
            )}
          </div>
          {rows !== null && (
            <ul className="tv-sp-stats">
              {rows.map((row) => (
                <li key={row.label}>
                  <span>{row.label}</span>
                  <strong>{row.count.toLocaleString("en-US")}</strong>
                </li>
              ))}
            </ul>
          )}
          {rows !== null && total === 0 && (
            <div className="tv-sp-note">
              <p className="tv-sp-note-title">Queue clear</p>
              <p>No open reports and nothing held by the spam firewall.</p>
            </div>
          )}
        </>
      )}
    </>
  );
}
