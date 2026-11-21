import { type ReactNode } from "react";
import { ArtIcon } from "../../../components/ArtIcon";
import { getUnread, listThreads } from "../../messaging/api";
import { optBool } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const messagingWidget: WidgetDef = {
    icon: <ArtIcon name="messages" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the two count lines each get a switch,
      // and the newest conversation names ride under the
      // counts. That costs the design's ONE flagged extra
      // read — the conversation list the Messages page
      // loads — asked for only while the names are
      // switched on. At full width each row gains that
      // conversation's own unread count.
      const settings = ctx?.settings ?? {};
      const showUnread = optBool(settings, "showUnread", true);
      const showRequests = optBool(settings, "showRequests", true);
      const showConversations = optBool(settings, "showConversations", true);
      const u = await getUnread();
      const lines: string[] = [];
      if (showUnread) {
        lines.push(line(t, "home.widget.unread", "{count} unread messages", { count: count(u.inbox_unread) }));
      }
      if (showRequests) {
        lines.push(line(t, "home.widget.messageRequests", "{count} message requests", { count: count(u.requests_count) }));
      }
      const data: WidgetData = { lines };
      if (showConversations) {
        const threads = await listThreads("inbox");
        if (threads.length > 0) {
          const full = ctx?.size === "full";
          if (full) {
            data.header = [
              line(t, "home.widget.colConversation", "Conversation"),
              line(t, "home.widget.colUnread", "Unread"),
            ];
          }
          data.rowsClass = "tv-widget-rows--cols-messaging";
          data.rows = threads.slice(0, 5).map((th) => {
            const cells: ReactNode[] = [th.other_name];
            if (full) cells.push(th.unread_count > 0 ? count(th.unread_count) : "—");
            return { cells };
          });
        }
      }
      return data;
    },
  };
