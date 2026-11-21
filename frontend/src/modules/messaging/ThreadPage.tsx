import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  Panel,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import {
  completeThread,
  getThreadCompletion,
} from "../marketplace/api";
import type { ThreadCompletion } from "../marketplace/types";
import {
  acceptRequest,
  blockUser,
  declineRequest,
  getThread,
  markRead,
  postMessage,
  reportThread,
} from "./api";
import type { MessageItem, ThreadDetail } from "./types";

const URL_RE = /(https?:\/\/[^\s]+|www\.[^\s]+)/g;

/** Message body with links: LIVE anchors only when the thread is
 *  past the request stage (and the message carries none of the
 *  hold states); inert text + styling otherwise — the quarantine
 *  rule the API reports via links_disabled. */
function BodyText({ message }: { message: MessageItem }) {
  if (message.removed) {
    return <em style={{ color: "var(--text-muted)" }}>Message removed</em>;
  }
  const parts = message.body.split(URL_RE);
  return (
    <>
      {parts.map((part, i) => {
        const isUrl = /^https?:\/\//.test(part) || /^www\./.test(part);
        if (!isUrl) return <span key={i}>{part}</span>;
        if (message.links_disabled || message.held) {
          return (
            <span
              key={i}
              style={{ textDecoration: "underline dotted", color: "var(--text-muted)" }}
              title="Links are disabled until this conversation is accepted."
            >
              {part}
            </span>
          );
        }
        const href = part.startsWith("www.") ? `https://${part}` : part;
        return (
          <a key={i} href={href} target="_blank" rel="noreferrer noopener">
            {part}
          </a>
        );
      })}
    </>
  );
}

function ThreadContent() {
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [thread, setThread] = useState<ThreadDetail | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState("");
  const [completion, setCompletion] = useState<ThreadCompletion | null>(null);
  const [closing, setClosing] = useState(false);
  const markedRef = useRef<string>("");

  const load = useCallback(async () => {
    if (!threadId) return;
    try {
      const detail = await getThread(threadId);
      setThread(detail);
      // Deal completion rides along for anchored threads (the
      // marketplace owns deal state; messaging keeps none). A
      // failure here never breaks the conversation view.
      if (detail.anchor_type) {
        getThreadCompletion(threadId)
          .then(setCompletion)
          .catch(() => setCompletion(null));
      }
      // Reading an accepted thread marks it read (once per newest
      // incoming message, not on every poll).
      const newestIncoming = [...detail.messages]
        .reverse()
        .find((m) => !m.mine && !m.held && !m.removed);
      if (
        detail.status === "accepted" &&
        newestIncoming &&
        markedRef.current !== newestIncoming.id
      ) {
        markedRef.current = newestIncoming.id;
        void markRead(threadId).catch(() => undefined);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load that conversation.");
    }
  }, [threadId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!threadId || !draft.trim()) return;
    setSending(true);
    try {
      await postMessage(threadId, draft.trim());
      setDraft("");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't send.", {
        title: "Message not sent",
        tone: "danger",
      });
    } finally {
      setSending(false);
    }
  }

  async function onAccept() {
    if (!threadId) return;
    try {
      await acceptRequest(threadId);
      toast("Conversation accepted — it's in your inbox now.", {
        title: "Accepted",
        tone: "success",
      });
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't accept.", {
        title: "Something went wrong",
        tone: "danger",
      });
    }
  }

  async function onDecline() {
    if (!threadId) return;
    try {
      await declineRequest(threadId);
      navigate("/messages");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't decline.", {
        title: "Something went wrong",
        tone: "danger",
      });
    }
  }

  async function onBlock() {
    if (!thread) return;
    try {
      await blockUser(thread.other_user_id);
      toast(
        `${thread.other_name || "That member"} is blocked. They won't be told, and their messages won't reach you.`,
        { title: "Blocked", tone: "success", duration: 8000 },
      );
      navigate("/messages");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't block.", {
        title: "Something went wrong",
        tone: "danger",
      });
    }
  }

  async function onReport(event: FormEvent) {
    event.preventDefault();
    if (!threadId) return;
    try {
      await reportThread(threadId, reportReason.trim());
      setReportOpen(false);
      setReportReason("");
      toast("Reported. A moderator will review this conversation.", {
        title: "Report sent",
        tone: "success",
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't report.", {
        title: "Something went wrong",
        tone: "danger",
      });
    }
  }

  if (error) {
    return (
      <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
        <Breadcrumbs items={[{ label: "Messages", to: "/messages" }, { label: "Conversation" }]} />
        <Alert tone="danger">{error}</Alert>
      </div>
    );
  }
  if (!thread) return <Spinner />;

  const incoming = thread.direction === "incoming";
  const isRequest = thread.status === "request";
  const readByOther =
    thread.other_last_read_seq !== null &&
    thread.messages.length > 0 &&
    thread.other_last_read_seq >= thread.messages[thread.messages.length - 1].seq;

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
      <Breadcrumbs
        items={[
          { label: "Messages", to: "/messages" },
          { label: thread.other_name || "Conversation" },
        ]}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.6rem" }}>
        <h1 style={{ margin: 0 }}>{thread.other_name || "Member"}</h1>
        <Link to={`/users/${thread.other_user_id}`}>View profile</Link>
      </div>

      {thread.anchor_title && (
        <Alert tone="info">
          This conversation is about: <strong>{thread.anchor_title}</strong>
          {thread.anchor_type === "part" && (
            <>
              {" — see it in "}
              <Link to="/parts/community">Community Parts</Link>.
            </>
          )}
          {thread.anchor_type === "listing" && thread.anchor_id && (
            <>
              {" — see it in "}
              <Link to={`/marketplace/${thread.anchor_id}`}>Tools for sale</Link>.
            </>
          )}
        </Alert>
      )}

      {thread.anchor_type && completion && (
        <Panel title="Completed deal?">
          {completion.interaction_id ? (
            <p style={{ margin: 0 }}>
              You both marked this conversation as a completed deal.{" "}
              <Link to="/marketplace/mine">Rate it under My deals</Link> —
              ratings stay private until you've both submitted, or 14
              days pass.
            </p>
          ) : completion.i_closed ? (
            <p style={{ margin: 0 }}>
              You've marked this as a completed deal. It becomes
              rateable once {thread.other_name || "the other side"} marks
              it too.
            </p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              <p style={{ margin: 0 }}>
                Did this conversation end in a deal? Marking it completed
                {completion.other_closed
                  ? " — the other side already has"
                  : ""}{" "}
                lets you both rate each other once you've both marked it.
              </p>
              <div>
                <Button
                  type="button"
                  loading={closing}
                  onClick={() => {
                    if (!threadId) return;
                    setClosing(true);
                    completeThread(threadId)
                      .then((state) => {
                        setCompletion(state);
                        toast(
                          state.interaction_id
                            ? "Deal completed — you can both rate it now."
                            : "Marked. It completes when the other side marks it too.",
                          { title: "Done", tone: "success" },
                        );
                      })
                      .catch((err) =>
                        toast(
                          err instanceof ApiError
                            ? err.message
                            : "Couldn't mark that.",
                          { title: "Something went wrong", tone: "danger" },
                        ),
                      )
                      .finally(() => setClosing(false));
                  }}
                >
                  Mark as completed deal
                </Button>
              </div>
            </div>
          )}
        </Panel>
      )}

      {isRequest && incoming && (
        <Panel title="Message request">
          <p style={{ marginTop: 0 }}>
            This member hasn't messaged you before. Until you accept,
            this conversation stays out of your inbox, links in it are
            disabled, and they can't see whether you've read it.
            Replying accepts the conversation.
          </p>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            <Button type="button" onClick={() => void onAccept()}>
              Accept
            </Button>
            <Button type="button" variant="secondary" onClick={() => void onDecline()}>
              Decline
            </Button>
          </div>
        </Panel>
      )}
      {isRequest && !incoming && (
        <Alert tone="warning">
          Request sent. {thread.other_name || "They"} hasn't accepted
          yet — you'll get a note when they reply, and read receipts
          start then.
        </Alert>
      )}

      <Panel>
        <div style={{ display: "grid", gap: "0.7rem" }}>
          {thread.messages.length === 0 && (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Nothing here yet.
            </p>
          )}
          {thread.messages.map((message) => (
            <div
              key={message.id}
              style={{
                justifySelf: message.mine ? "end" : "start",
                maxWidth: "82%",
                display: "grid",
                gap: "0.2rem",
              }}
            >
              <div
                className={`tv-msg-bubble${message.mine ? " tv-msg-bubble--mine" : ""}${message.held ? " tv-msg-bubble--held" : ""}${message.links_disabled ? " tv-msg-bubble--quarantine" : ""}`}
                style={{
                  padding: "0.55rem 0.8rem",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  background: message.mine ? "var(--surface-raised, transparent)" : undefined,
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                }}
              >
                <BodyText message={message} />
              </div>
              <span
                style={{
                  fontSize: "0.78rem",
                  color: "var(--text-muted)",
                  display: "flex",
                  gap: "0.5rem",
                  flexWrap: "wrap",
                  justifyContent: message.mine ? "flex-end" : "flex-start",
                }}
              >
                {new Date(message.created_at).toLocaleString([], {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}
                {message.held && (
                  <Badge tone="warning">Under review — not delivered yet</Badge>
                )}
                {message.has_links && !message.links_disabled && !message.held && (
                  <Badge tone="warning">External link — check before you trust it</Badge>
                )}
              </span>
            </div>
          ))}
          {!isRequest && readByOther && (
            <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", textAlign: "right" }}>
              Read
            </span>
          )}
        </div>
      </Panel>

      <form onSubmit={(e) => void onSend(e)} style={{ display: "grid", gap: "0.6rem" }}>
        <TextArea
          aria-label="Write a message"
          rows={3}
          placeholder={
            isRequest && incoming
              ? "Reply to accept this conversation…"
              : "Write a message…"
          }
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <Button type="submit" disabled={sending || !draft.trim()}>
            {sending ? "Sending…" : "Send"}
          </Button>
          <Button type="button" variant="secondary" onClick={() => setReportOpen((v) => !v)}>
            Report
          </Button>
          <Button type="button" variant="danger" onClick={() => void onBlock()}>
            Block {thread.other_name || "member"}
          </Button>
        </div>
      </form>

      {reportOpen && (
        <Panel title="Report this conversation">
          <form onSubmit={(e) => void onReport(e)} style={{ display: "grid", gap: "0.6rem" }}>
            <TextInput
              aria-label="Why are you reporting this?"
              placeholder="What happened? (a moderator reads the thread)"
              value={reportReason}
              onChange={(e) => setReportReason(e.target.value)}
            />
            <div>
              <Button type="submit">Send report</Button>
            </div>
          </form>
        </Panel>
      )}
    </div>
  );
}

export default function ThreadPage() {
  return (
    <RequireAuth>
      <ThreadContent />
    </RequireAuth>
  );
}
