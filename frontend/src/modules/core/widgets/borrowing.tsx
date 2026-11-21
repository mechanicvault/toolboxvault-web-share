import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, HrefButton, Modal, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { useT } from "../../../i18n/LocaleContext";
import { formatDate } from "../../../lib/format";
import { getBorrowingOverview, nudgeCheckout } from "../../borrowing/api";
import { itemPath } from "../../borrowing/format";
import type { Checkout, NudgeResult } from "../../borrowing/types";
import { CopyButton } from "../../../components/CopyButton";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetRowGroup, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

function BorrowNudgeButton({ checkout }: { checkout: Checkout }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [copy, setCopy] = useState<NudgeResult | null>(null);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const send = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await nudgeCheckout(checkout.id);
      if (result.delivered_via === "message") {
        setSent(true);
      } else {
        setCopy(result);
      }
    } catch {
      setError(
        line(t, "home.widget.borrowNudgeError", "Couldn't send that reminder."),
      );
    } finally {
      setBusy(false);
    }
  };
  const contact = checkout.borrower_contact || "";
  const email = contact.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0];
  const phone = contact.replace(/[^0-9+]/g, "");
  return (
    <>
      <Button type="button" size="sm" disabled={busy || sent} onClick={send}>
        {sent
          ? line(t, "home.widget.borrowNudgeSent", "Reminder sent")
          : line(t, "home.widget.borrowNudge", "Send reminder")}
      </Button>
      {error && (
        <span className="tv-widget-entry-error" role="alert">
          {error}
        </span>
      )}
      <Modal
        open={copy !== null}
        onClose={() => setCopy(null)}
        title={
          copy
            ? line(t, "home.widget.borrowNudgeTitle", "Nudge {name}", {
                name: checkout.borrower_name,
              })
            : undefined
        }
        footer={
          <Button type="button" variant="secondary" onClick={() => setCopy(null)}>
            {line(t, "home.widget.borrowNudgeClose", "Close")}
          </Button>
        }
      >
        {copy && (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              {line(
                t,
                "home.widget.borrowNudgeExplain",
                "{name} isn't linked to a Toolbox Vault account we can message — here's the reminder, ready to send your usual way:",
                { name: checkout.borrower_name },
              )}
            </p>
            <div
              style={{
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                padding: "0.7rem 0.9rem",
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
              }}
            >
              {copy.message}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <CopyButton
                text={copy.message}
                label={line(t, "home.widget.borrowNudgeCopy", "Copy message")}
              />
              {phone.length >= 7 && (
                <>
                  <HrefButton href={`tel:${phone}`} variant="secondary">
                    {line(t, "home.widget.borrowNudgeCall", "Call")}
                  </HrefButton>
                  <HrefButton
                    href={`sms:${phone}?&body=${encodeURIComponent(copy.message)}`}
                    variant="secondary"
                  >
                    {line(t, "home.widget.borrowNudgeText", "Text it")}
                  </HrefButton>
                </>
              )}
              {email && (
                <HrefButton
                  href={`mailto:${email}?subject=${encodeURIComponent("Friendly reminder")}&body=${encodeURIComponent(copy.message)}`}
                  variant="secondary"
                >
                  {line(t, "home.widget.borrowNudgeEmail", "Email it")}
                </HrefButton>
              )}
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}


export const borrowingWidget: WidgetDef = {
    icon: <ArtIcon name="borrowing" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 2: the lent-out list as real rows
      // (the owner's ask — who has what), a borrowed-by-me
      // list, overdue names, and the requests line, all from
      // the ONE overview this widget has always loaded. At
      // full width the two lists sit side by side, each
      // scrolling on its own; the counts line stays on top
      // and the waiting/overdue lines keep their place under
      // the lists, as they read today.
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const lentList = optBool(settings, "lentList", true);
      const borrowedList = optBool(settings, "borrowedList", false);
      const overdueNames = optBool(settings, "overdueNames", false);
      const requestsLine = optBool(settings, "requestsLine", true);
      const visibleRows = optNum(settings, "visibleRows", 3, 2, 6);
      const o = await getBorrowingOverview();
      // Sample redesign (2026-11-15): the overdue banner with
      // its Send reminder on top, the counts line, the two
      // lists as ruled rows with standing pills, and the
      // footer pair. Row click goes to the item's Borrowing
      // tab (the standing borrowing rule).
      const pillFor = (c: Checkout) => {
        if (c.overdue) {
          return (
            <Badge tone="danger">
              {line(t, "home.widget.borrowPillOverdue", "Overdue")}
            </Badge>
          );
        }
        if (c.due_at) {
          const days = Math.ceil(
            (new Date(c.due_at).getTime() - Date.now()) / 86400000,
          );
          if (days >= 0 && days <= 14) {
            return (
              <Badge tone="warning">
                {line(t, "home.widget.borrowPillDueIn", "Due in {days} days", {
                  days: count(days),
                })}
              </Badge>
            );
          }
        }
        return (
          <Badge tone="neutral">
            {line(t, "home.widget.borrowPillOut", "Out")}
          </Badge>
        );
      };
      const groups: WidgetRowGroup[] = [];
      if (lentList && o.lent_out.length > 0) {
        groups.push({
          label: line(t, "home.widget.lentOut", "Lent out"),
          rows: o.lent_out.slice(0, visibleRows).map((c) => ({
            cells: [
              <span key="item" className="tv-widget-cellstack">
                <span>{c.item_name}</span>
                <span className="tv-widget-cellsub">
                  {line(t, "home.widget.borrowTo", "to {name}", {
                    name: c.borrower_name,
                  })}
                  {c.due_at
                    ? ` · ${line(t, "home.widget.borrowDueWord", "due")} ${formatDate(c.due_at)}`
                    : ""}
                </span>
              </span>,
              pillFor(c),
            ],
            href: `${itemPath(c)}#borrowing`,
          })),
          rowsClass: "tv-widget-rows--reports",
        });
      }
      if (borrowedList && o.borrowed_by_me.length > 0) {
        groups.push({
          label: line(t, "home.widget.borrowedByMe", "Borrowed by me"),
          rows: o.borrowed_by_me.slice(0, visibleRows).map((c) => ({
            cells: [
              <span key="item" className="tv-widget-cellstack">
                <span>{c.item_name}</span>
                <span className="tv-widget-cellsub">
                  {line(t, "home.widget.borrowFrom", "from {name}", {
                    name: c.owner_name ?? "",
                  })}
                  {c.due_at
                    ? ` · ${line(t, "home.widget.borrowDueWord", "due")} ${formatDate(c.due_at)}`
                    : ""}
                </span>
              </span>,
              pillFor(c),
            ],
            href: `${itemPath(c)}#borrowing`,
          })),
          rowsClass: "tv-widget-rows--reports",
        });
      }
      const linesAfter: string[] = [];
      if (requestsLine && o.counts.pending_requests > 0) {
        linesAfter.push(line(t, "home.widget.requestsWaiting", "{count} requests waiting on you", { count: count(o.counts.pending_requests) }));
      }
      if (overdueNames) {
        for (const c of o.lent_out.filter((x) => x.overdue)) {
          linesAfter.push(line(t, "home.widget.overdueWith", "Overdue: {item} — with {name}", { item: c.item_name, name: c.borrower_name }));
        }
        for (const c of o.borrowed_by_me.filter((x) => x.overdue)) {
          linesAfter.push(line(t, "home.widget.overdueFrom", "Overdue: {item} — from {name}", { item: c.item_name, name: c.owner_name ?? "" }));
        }
      }
      const data: WidgetData = { lines: [] };
      const firstOverdueLent = o.lent_out.find((c) => c.overdue);
      if (firstOverdueLent && !ctx?.editing) {
        const c = firstOverdueLent;
        data.banner = (
          <div className="tv-borrow-banner-in">
            <div className="tv-borrow-banner-text">
              <strong>
                {line(t, "home.widget.borrowBannerTitle", "{item} is overdue", {
                  item: c.item_name,
                })}
              </strong>
              <span>
                {c.borrower_name}
                {c.checked_out_at
                  ? ` · ${line(t, "home.widget.borrowBannerLent", "Lent {date}", { date: formatDate(c.checked_out_at) })}`
                  : ""}
                {c.due_at
                  ? ` · ${line(t, "home.widget.borrowBannerDue", "was due back {date}", { date: formatDate(c.due_at) })}`
                  : ""}
              </span>
            </div>
            <BorrowNudgeButton checkout={c} />
          </div>
        );
      }
      if (showCounts) {
        data.counts = [
          {
            value: count(o.lent_out.length),
            label: line(t, "home.widget.borrowWordLent", "lent out"),
          },
          {
            value: count(o.borrowed_by_me.length),
            label: line(t, "home.widget.borrowWordBorrowed", "borrowed by me"),
          },
        ];
        if (o.counts.overdue > 0) {
          data.counts.push({
            value: count(o.counts.overdue),
            label: line(t, "home.widget.borrowWordOverdue", "overdue"),
          });
        }
      }
      if (groups.length > 0) data.groups = groups;
      if (linesAfter.length > 0) data.linesAfter = linesAfter;
      data.actionsEnd = true;
      data.actions = (
        <>
          <Link to="/shared-tools#borrowing" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.borrowOpen", "Open borrowing")}
          </Link>
          <Link to="/shared-tools#borrowing" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.borrowLend", "Lend a tool")}
          </Link>
        </>
      );
      return data;
    },
  };
