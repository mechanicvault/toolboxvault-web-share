import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Panel,
  Spinner,
  TextInput,
  useToast,
  LinkButton,
} from "../../components";
import { ApiError } from "../../lib/api";
import { RequireAuth, useAuth } from "../core";
import {
  listBlocks,
  listThreads,
  lookupRecipient,
  openThread,
  unblockUser,
} from "./api";
import type { BlockItem, ThreadSummary } from "./types";

type Tab = "inbox" | "requests" | "blocked";

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function ThreadRow({ thread }: { thread: ThreadSummary }) {
  return (
    <Link
      to={`/messages/${thread.id}`}
      className={`tv-msg-row${thread.unread_count > 0 ? " is-unread" : ""}`}
      style={{
        display: "grid",
        gap: "0.15rem",
        padding: "0.75rem 0.9rem",
        border: "1px solid var(--edge)",
        borderRadius: "var(--radius)",
        textDecoration: "none",
        color: "inherit",
        background: thread.unread_count > 0 ? "var(--surface-raised, transparent)" : undefined,
      }}
    >
      <span style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
        <strong>{thread.other_name || "Member"}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {when(thread.last_message_at ?? thread.created_at)}
        </span>
      </span>
      {thread.anchor_title && (
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          About: {thread.anchor_title}
        </span>
      )}
      <span
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "1rem",
          color: "var(--text-muted)",
        }}
      >
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: "70%",
          }}
        >
          {thread.last_message_mine ? "You: " : ""}
          {thread.last_message_preview || "—"}
        </span>
        {thread.unread_count > 0 && (
          <Badge tone="accent">{thread.unread_count} new</Badge>
        )}
        {thread.status === "request" && thread.direction === "outgoing" && (
          <Badge tone="warning">Request sent</Badge>
        )}
      </span>
    </Link>
  );
}

function NewConversation() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [accountNumber, setAccountNumber] = useState("");
  const [found, setFound] = useState<{ user_id: string; display_name: string } | null>(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onLookup(event: FormEvent) {
    event.preventDefault();
    setError("");
    setFound(null);
    try {
      setFound(await lookupRecipient(accountNumber.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't look that up.");
    }
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!found || !body.trim()) return;
    setBusy(true);
    setError("");
    try {
      const thread = await openThread({ recipient_id: found.user_id, body: body.trim() });
      toast("Message sent. Until they reply, it waits in their message requests.", {
        title: "Sent",
        tone: "success",
      });
      navigate(`/messages/${thread.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send that message.");
      setBusy(false);
    }
  }

  return (
    <Panel title="Start a conversation">
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Enter the other member's account number (it looks like TV-MS-000159).
        Most conversations start from a Community Parts listing or a
        member's profile — this is the direct way.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <form onSubmit={(e) => void onLookup(e)} style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px" }}>
          <TextInput
            aria-label="Account number"
            placeholder="TV-MS-000159"
            value={accountNumber}
            onChange={(e) => setAccountNumber(e.target.value)}
          />
        </div>
        <Button type="submit" variant="secondary">
          Find member
        </Button>
      </form>
      {found && (
        <form
          onSubmit={(e) => void onSend(e)}
          style={{ display: "grid", gap: "0.6rem", marginTop: "0.9rem" }}
        >
          <FormField label={`Message to ${found.display_name}`} htmlFor="new-msg-body">
            <TextInput
              id="new-msg-body"
              placeholder="Say what you're after…"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </FormField>
          <div>
            <Button type="submit" disabled={busy || !body.trim()}>
              {busy ? "Sending…" : "Send message"}
            </Button>
          </div>
        </form>
      )}
    </Panel>
  );
}

function MessagesContent() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("inbox");
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [blocks, setBlocks] = useState<BlockItem[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      if (tab === "blocked") {
        setBlocks(await listBlocks());
      } else {
        setThreads(await listThreads(tab));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load messages.");
    }
  }, [tab]);

  useEffect(() => {
    void load();
    // Near-time refresh: poll quietly while the page is open.
    const timer = window.setInterval(() => void load(), 20000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function onUnblock(item: BlockItem) {
    try {
      await unblockUser(item.user_id);
      toast(`${item.name || "That member"} can message you again.`, {
        title: "Unblocked",
        tone: "success",
      });
      void load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't unblock.", {
        title: "Something went wrong",
        tone: "danger",
      });
    }
  }

  const isMod =
    user?.is_operator || user?.role === "moderator" || user?.role === "community_admin";

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.6rem" }}>
        <h1 style={{ margin: 0 }}>Messages</h1>
        {isMod && (
          <LinkButton to="/moderation" variant="secondary">Moderation queue</LinkButton>
        )}
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }} role="tablist">
        {(
          [
            ["inbox", "Inbox"],
            ["requests", "Requests"],
            ["blocked", "Blocked"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <Button
            key={key}
            type="button"
            variant={tab === key ? "primary" : "secondary"}
            onClick={() => setTab(key)}
          >
            {label}
          </Button>
        ))}
      </div>

      {tab === "blocked" ? (
        blocks === null ? (
          <Spinner />
        ) : blocks.length === 0 ? (
          <Panel title="Blocked members">
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              Nobody is blocked. Blocking someone (from inside a
              conversation) is silent: their messages simply never
              reach you, and they're never told.
            </p>
          </Panel>
        ) : (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {blocks.map((item) => (
              <div
                key={item.user_id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                  padding: "0.6rem 0.9rem",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                }}
              >
                <span>{item.name || "Member"}</span>
                <Button type="button" variant="secondary" onClick={() => void onUnblock(item)}>
                  Unblock
                </Button>
              </div>
            ))}
          </div>
        )
      ) : threads === null ? (
        <Spinner />
      ) : threads.length === 0 ? (
        <Panel title={tab === "requests" ? "No requests waiting" : "No conversations yet"}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            {tab === "requests"
              ? "When someone messages you for the first time, their conversation lands here first. Replying accepts it — nothing reaches your inbox or email until you do."
              : "Conversations you start — and requests you've answered — live here. Ask about a part in Community Parts, open a member's profile, or start one below."}
          </p>
        </Panel>
      ) : (
        <div style={{ display: "grid", gap: "0.6rem" }}>
          {threads.map((thread) => (
            <ThreadRow key={thread.id} thread={thread} />
          ))}
        </div>
      )}

      <NewConversation />
    </div>
  );
}

export default function MessagesPage() {
  return (
    <RequireAuth>
      <MessagesContent />
    </RequireAuth>
  );
}
