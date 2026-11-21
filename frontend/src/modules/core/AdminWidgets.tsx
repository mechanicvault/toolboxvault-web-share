/** Admin Home widgets (admin lane, owner 2026-11-06; polish
 *  lane, owner corrections 2026-11-07): the five responder-side
 *  blocks — Support Tickets, Bug Reports, Feature Requests,
 *  Forum Moderator, Site Stats — registered in CorePage ONLY
 *  for god + moderator_admin seats, so the blocks (and their
 *  Edit-view Add entries) never exist for anyone else.
 *
 *  POLISH (2026-11-07): the widgets now wear the STANDARD Home
 *  widget chrome — the same Panel, the whole-box cover link
 *  (which is what earns the Main highlight lift + glow), the
 *  head row with the ArtIcon tile + title + Open CTA seat, and
 *  stat rows at the standard widgets' compact line rhythm —
 *  instead of the admin lane's flat panel with a footer door
 *  button. Each widget has its own real ArtIcon artwork. Every
 *  stat ROW is individually toggleable in the widget's options
 *  (no grouped toggles; a line that's off leaves no gap). The
 *  Site Stats widget mirrors the admin Site Overview report:
 *  member-type counts and paying-by-plan rows ride along, each
 *  with its own toggle and its own day-over-day delta when the
 *  daily snapshot has a baseline for it.
 *
 *  All five read ONE endpoint — GET /api/admin/home-widgets,
 *  itself tier-gated server-side — through a shared cached
 *  loader, so a Home full of admin widgets costs one fetch.
 *  Rows and doors go inert in Home Edit view, like every other
 *  block. Deltas come from the daily snapshot; with no earlier
 *  snapshot (or none holding the newer dimensions) the widget
 *  says so plainly instead of inventing a baseline.
 */
import "./adminWidgets.css";

export { AdminTicketsWidget } from "./admin/tickets";
export { AdminBoardWidget } from "./admin/board";
export { AdminForumModeratorWidget } from "./admin/forumModerator";
export { AdminSiteStatsWidget } from "./admin/siteStats";
export { AdminOverviewWidget } from "./admin/overview";
export { AdminScoreboardWidget } from "./admin/scoreboard";
export { AdminHealthWidget } from "./admin/health";
