import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatDate, formatDateTime } from "../../../lib/format";
import { listMyTickets } from "../../support/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const supportWidget: WidgetDef = {
    icon: <ArtIcon name="support" size={24} />,
    tone: "warning",
    cta: "open",
    path: "/help",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the open tickets
      // ride as rows — subject, and at full width the last
      // time the ticket moved — each row a link into that
      // very ticket on the Help page (its ?ticket= deep
      // link, the standing door). The rows take the place
      // of today's single Latest line, as the Claims rows
      // did; the full list already loads to count them.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const rowsToShow = optNum(settings, "rowsToShow", 3, 1, 5);
      // Custom-widget aspect gate (Lane 2): the ticket rows
      // carry their own switch, defaulting ON — absence is
      // today's widget exactly.
      const showRows = optBool(settings, "showRows", true);
      const tickets = await listMyTickets();
      const open = tickets.filter((tk) => tk.status !== "closed");
      // The widget carries real information now (owner,
      // 2026-11-14: it "looks shitty with little to no
      // information"): the counts ride as stat tiles — open,
      // waiting on the member (the team's reply is newest),
      // closed — and each ticket row names where it stands
      // and when it last moved, with the newest message's
      // opening words under the subject.
      // Sample redesign (2026-11-15): the explainer sub-line,
      // the three standing tiles (already the sample's), the
      // tickets as a YOUR TICKETS group, and the footer pair.
      const data: WidgetData = {
        lines: [
          line(
            t,
            "home.widget.supportSub",
            "Your help requests with the Toolbox Vault team",
          ),
        ],
      };
      if (showCount) {
        data.stats = [
          {
            label: line(t, "home.widget.statOpenTickets", "Open tickets"),
            value: count(open.length),
          },
          {
            label: line(t, "home.widget.statWaitingOnYou", "Waiting on you"),
            value: count(
              open.filter((tk) => tk.last_message_author_kind === "operator")
                .length,
            ),
            tone:
              open.filter((tk) => tk.last_message_author_kind === "operator")
                .length > 0
                ? "warn"
                : undefined,
          },
          {
            label: line(t, "home.widget.statClosedTickets", "Closed"),
            value: count(tickets.length - open.length),
            tone: "good",
          },
        ];
      }
      if (showRows && open.length > 0) {
        const full = ctx?.size === "full";
        data.groups = [
          {
            label: line(t, "home.widget.supportGroup", "Your tickets"),
            header: full
              ? [
                  line(t, "home.widget.colSubject", "Subject"),
                  line(t, "home.widget.colStatus", "Status"),
                  line(t, "home.widget.colUpdated", "Last updated"),
                ]
              : undefined,
            rowsClass: "tv-widget-rows--reports",
            rows: open.slice(0, rowsToShow).map((tk) => {
              const cells: ReactNode[] = [
                <span key="subject" className="tv-widget-cellstack">
                  <span>{tk.subject}</span>
                  <span className="tv-widget-cellsub">
                    {tk.last_message_preview ||
                      line(t, "home.widget.supportUpdated", "Updated {date}", {
                        date: formatDate(tk.updated_at),
                      })}
                  </span>
                </span>,
                <Badge
                  key="status"
                  tone={tk.status === "open" ? "accent" : "neutral"}
                >
                  {line(
                    t,
                    tk.status === "open"
                      ? "help.statusOpen"
                      : tk.status === "under_review"
                        ? "help.statusUnderReview"
                        : "help.statusClosed",
                    tk.status,
                  )}
                </Badge>,
              ];
              if (full) cells.push(formatDateTime(tk.updated_at));
              return { cells, href: `/help?ticket=${tk.id}` };
            }),
          },
        ];
      }
      data.actionsEnd = true;
      data.actions = (
        <>
          <Link to="/help#tickets" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.supportAll", "All tickets")}
          </Link>
          <Link to="/help" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.supportNew", "New ticket")}
          </Link>
        </>
      );
      return data;
    },
  };
