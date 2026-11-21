import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { api } from "../../../lib/api";
import { formatDate } from "../../../lib/format";
import type { PeerOverview } from "../../peer/types";
import { optBool } from "../widgetOptions";
import type { WidgetRowGroup, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const sharedToolsWidget: WidgetDef = {
    icon: <ArtIcon name="shared" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): the explainer line,
      // the counts, then the two directions as MINI TABLES
      // with column heads — who you share with (their tool
      // count as a badge, sharing since) and who shares
      // with you (how much you can see, standing). The
      // grants carry no view-activity stamp, so the third
      // column is the honest one: when the sharing began.
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const showInvites = optBool(settings, "showInvites", true);
      const showMine = optBool(settings, "showMine", true);
      const showWithMe = optBool(settings, "showWithMe", true);
      const o = await api<PeerOverview>("/core/sharing/peer");
      const mine = o.sharing_with.filter((g) => g.status === "accepted");
      const withMe = o.shared_with_me.filter((g) => g.status === "accepted");
      const data: WidgetData = { lines: [] };
      if (showCounts) {
        data.lines.push(
          line(
            t,
            "home.widget.sharedExplainer",
            "Share your list with specific people — they see only what you choose.",
          ),
        );
        data.counts = [
          {
            value: count(mine.length),
            label: line(t, "home.widget.sharedYouShare", "you share with"),
          },
          {
            value: count(withMe.length),
            label: line(t, "home.widget.sharedWithYouWord", "share with you"),
          },
        ];
        if (showInvites && o.pending_for_me.length > 0) {
          data.counts.push({
            value: count(o.pending_for_me.length),
            label: line(t, "home.widget.sharedInvitesWord", "invites waiting"),
          });
        }
      }
      const groups: WidgetRowGroup[] = [];
      if (showMine) {
        const mineRows = mine
          .filter((g) => g.viewer !== null)
          .map((g) => ({
            cells: [
              g.viewer!.name,
              <Badge key="n" tone="neutral">{count(g.tool_count)}</Badge>,
              formatDate((g.responded_at ?? g.created_at).slice(0, 10)),
            ],
          }));
        if (mineRows.length > 0) {
          groups.push({
            label: line(t, "home.widget.youShareWith", "You share with"),
            header: [
              line(t, "home.widget.sharedColPerson", "Person"),
              line(t, "home.widget.sharedColTools", "Tools"),
              line(t, "home.widget.sharedColSince", "Since"),
            ],
            rowsClass: "tv-widget-rows--cols-shared3 tv-widget-rows--ruled",
            rows: mineRows,
            visible: 4,
          });
        }
      }
      if (showWithMe && withMe.length > 0) {
        groups.push({
          label: line(t, "home.widget.sharedWithYou", "Shared with you"),
          header: [
            line(t, "home.widget.sharedColName", "Name"),
            line(t, "home.widget.sharedColDetails", "Details"),
            line(t, "home.widget.sharedColStatus", "Status"),
          ],
          rowsClass: "tv-widget-rows--cols-shared3 tv-widget-rows--ruled",
          rows: withMe.map((g) => ({
            cells: [
              g.owner.name,
              line(t, "home.widget.sharedSeesYours", "Shares {count} tools with you", {
                count: count(g.tool_count),
              }),
              <Badge key="s" tone="success">
                {line(t, "home.widget.sharedActive", "Active")}
              </Badge>,
            ],
          })),
          visible: 4,
        });
      }
      // Sheet row 51 (owner, 2026-11-15): invites I sent that
      // are still waiting on a reply were invisible here —
      // the tables above carry accepted shares only, so an
      // account whose sharing is all pending read as a bare
      // 0 / 0. The waiting invites ride as their own table:
      // who was invited (the address while it is unclaimed —
      // the flow never reveals whether it has an account),
      // how much they will see, and when it was sent.
      if (showMine) {
        const pending = o.sharing_with.filter(
          (g) => g.status === "pending",
        );
        if (pending.length > 0) {
          groups.push({
            label: line(
              t,
              "home.widget.sharedPendingGroup",
              "Waiting for a reply",
            ),
            header: [
              line(t, "home.widget.sharedColPerson", "Person"),
              line(t, "home.widget.sharedColTools", "Tools"),
              line(t, "home.widget.sharedColSince", "Since"),
            ],
            rowsClass: "tv-widget-rows--cols-shared3 tv-widget-rows--ruled",
            rows: pending.map((g) => ({
              cells: [
                g.viewer?.name ?? g.invited_email ?? "—",
                <Badge key="n" tone="neutral">{count(g.tool_count)}</Badge>,
                formatDate(g.created_at.slice(0, 10)),
              ],
            })),
            visible: 4,
          });
        }
      }
      if (groups.length > 0) data.groups = groups;
      data.actions = (
        <>
          <Link to="/shared-tools" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.sharedInvite", "Invite someone")}
          </Link>
          <Link to="/shared-tools" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.sharedOpen", "Open shared tools")}
          </Link>
        </>
      );
      data.actionsEnd = true;
      return data;
    },
  };
