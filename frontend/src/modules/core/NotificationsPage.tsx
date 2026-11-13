import { useNavigate } from "react-router-dom";

import { Button } from "../../components/Button";
import { useNotificationInbox } from "../../components/NotificationTicker";
import { Panel } from "../../components/Panel";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import { formatDateTime } from "../../lib/format";
import "./notifications.css";

/**
 * The full notifications page (Home + Header program, 2026-10-24):
 * the bell popup's "see all" target. Same inbox, whole list, with
 * the same verbs — mark read, mark all read, delete — so nothing
 * the popup promises is missing here.
 *
 * Click-through (owner spec 2026-10-25): the row's body is the
 * same button as the bell popup's — clicking it marks the
 * notification read AND goes to its source (the server-resolved
 * `link`). The explicit Mark read button stays for reading
 * without leaving; the × deletes and never navigates.
 *
 * List standard (2026-11-02): a true list — one notification per
 * row under a header row, facts in columns: status (the unread
 * marker) · notification (title over text) · category · time ·
 * actions. The text WRAPS inside its column instead of
 * truncating: a notification's text is the message itself (there
 * is no record page carrying it), so it is never cut off.
 */

/** Notification kind -> preference category, a client mirror of
 *  the server's KIND_CATEGORY (core/notification_prefs.py) — the
 *  same categories Settings -> Notifications names. A kind the
 *  map doesn't know lands in the account bucket, exactly like
 *  the server's category_for_kind default. */
const KIND_CATEGORY: Record<string, string> = {
  support_reply: "support",
  support_status: "support",
  support_ticket_new: "support",
  support_ticket_reply: "support",
  message_received: "messages",
  message_request_accepted: "messages",
  claim_deadline: "claims",
  claim_readiness: "claims",
  warranty_claim_new: "claims",
  warranty_claim_update: "claims",
  claim_backorder_reminder: "claims",
  borrow_requested: "borrowing",
  borrow_approved: "borrowing",
  borrow_declined: "borrowing",
  borrow_request_cancelled: "borrowing",
  borrow_returned: "borrowing",
  peer_invite_received: "sharing",
  peer_invite_accepted: "sharing",
  peer_invite_declined: "sharing",
  maintenance_overdue: "maintenance",
  forum_reply: "community",
  feedback_status_changed: "community",
  feedback_comment: "community",
  truck_invite_received: "truck_accounts",
  truck_account_accepted: "truck_accounts",
  truck_account_declined: "truck_accounts",
  truck_charge: "truck_accounts",
  truck_payment: "truck_accounts",
  truck_account_closed: "truck_accounts",
  truck_payment_due: "truck_accounts",
  truck_payment_overdue: "truck_accounts",
  truck_account_transferred: "truck_accounts",
  crew_invite_received: "crew",
  crew_invite_accepted: "crew",
  crew_invite_declined: "crew",
  crew_left: "crew",
  crew_grace_ending: "crew",
  crew_grace_expired: "crew",
  dealer_route_day: "dealers",
  agent_invite_reminder: "dealers",
  warranty_request_received: "dealers",
  warranty_request_claimed: "dealers",
  warranty_request_status: "dealers",
  feature_announcement: "announcements",
  cloud_backup_failed: "account",
  cloud_backup_recovered: "account",
  manual_saved: "account",
  manual_not_found: "account",
  rating_removed: "account",
};

function categoryKey(kind: string): DictKey {
  const category = KIND_CATEGORY[kind] ?? "account";
  return `settings.notifications.cat.${category}` as DictKey;
}

export default function NotificationsPage() {
  const t = useT();
  const navigate = useNavigate();
  const inbox = useNotificationInbox(true, 100);

  return (
    <div className="tv-stack">
      <div className="tv-title-row">
        <div>
          <h1>{t("notifications.title")}</h1>
          <p className="tv-muted">{t("notifications.intro")}</p>
        </div>
        <Button
          variant="secondary"
          disabled={inbox.unreadCount === 0}
          onClick={() => void inbox.markAllRead()}
        >
          {t("shell.markAllRead")}
        </Button>
      </div>
      {inbox.items.length === 0 ? (
        <Panel>
          <p className="tv-muted">{t("notifications.empty")}</p>
        </Panel>
      ) : (
        <div className="tv-notif-tablewrap">
          <div className="tv-notif-table" role="table">
            <div className="tv-notif-thead" role="row">
              <span role="columnheader">{t("notifications.col.status")}</span>
              <span role="columnheader">
                {t("notifications.col.notification")}
              </span>
              <span role="columnheader">{t("notifications.col.category")}</span>
              <span role="columnheader">{t("notifications.col.time")}</span>
              <span aria-hidden="true" />
            </div>
            {inbox.items.map((n) => (
              <div
                key={n.id}
                className="tv-notif-trow"
                role="row"
                data-read={n.read || undefined}
              >
                <div className="tv-notif-cell-status" role="cell">
                  <span
                    className="tv-notif-dot"
                    data-tone={n.tone}
                    aria-hidden="true"
                  />
                  <span>
                    {n.read
                      ? t("notifications.read")
                      : t("notifications.unread")}
                  </span>
                </div>
                <div role="cell">
                  <button
                    type="button"
                    className="tv-notif-main"
                    onClick={() => {
                      if (!n.read) void inbox.markRead(n.id);
                      if (n.link) navigate(n.link);
                    }}
                  >
                    <span className="tv-notif-title">{n.title}</span>
                    <span className="tv-notif-text">{n.text}</span>
                  </button>
                </div>
                <div className="tv-notif-cell-cat" role="cell">
                  {t(categoryKey(n.kind))}
                </div>
                <div className="tv-notif-cell-time" role="cell">
                  {formatDateTime(n.created_at)}
                </div>
                <div className="tv-notif-cell-actions" role="cell">
                  {!n.read && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void inbox.markRead(n.id)}
                    >
                      {t("shell.markRead")}
                    </Button>
                  )}
                  <button
                    type="button"
                    className="tv-bell-item-x"
                    aria-label={t("shell.deleteNotification")}
                    title={t("shell.deleteNotification")}
                    onClick={() => void inbox.remove(n.id)}
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
