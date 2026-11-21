/** Feedback boards — Bug Reports + Feature Requests (wave 3).
 *
 *  Reading is MEMBERS-ONLY (owner 2026-11-10, busy work #1 —
 *  supersedes the wave-3 public reading): the API refuses
 *  anonymous callers on both read faces, and these pages render
 *  a sign-in door (with a return path) for signed-out visitors
 *  — never the content, never a bare error. Posting is open to
 *  ANY signed-in account — free and downloads level included
 *  (the deliberate deviation from the forum's paid gate, Ryan's
 *  ruling: open feedback). The spam firewall still screens
 *  every write server-side; a held post shows its author a
 *  "held for review" badge and waits in the moderation queue.
 *
 *  IA (main tab layout, program lane 9, 2026-11-10): ONE
 *  tabbed page at /feedback — Bug Reports · Feature Requests
 *  tabs over this module's shared BoardBody — plus the post's
 *  own page at /feedback/post/:id. The old board routes
 *  (/feedback/bugs, /feedback/features) survive as doors:
 *  they redirect into the tabbed page at the matching tab
 *  (#bugs / #features), so every existing link — dashboard
 *  widgets, the forum's system boards, notification links,
 *  the board assistant — keeps landing on the right board.
 *  Removed posts leave the board listing (they read as
 *  tombstones on their own page); statuses are the roadmap:
 *  open → acknowledged → planned → in progress → done/declined.
 *  Done/declined posts are CLOSED (sweep E5, busy-work #7): the
 *  row and the post page say so in plain words, the comment form
 *  gives way to a closed notice (the thread stays readable),
 *  and a moderator moving the status back to an active one
 *  reopens the post in the same action.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import "./feedback.css";
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  EmptyState,
  FormField,
  LinkButton,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  Modal,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { useAuth } from "../core";
import {
  createComment,
  createPost,
  deleteComment,
  deletePost,
  getBoard,
  getMine,
  getPost,
  reportTarget,
  setPostStatus,
  setPostUrgency,
  toggleVote,
} from "./api";
import {
  STATUS_LABEL_KEYS,
  STATUS_LABELS,
  STATUS_TONES,
  type FeedbackBoard,
  type FeedbackPost,
  type FeedbackPostDetail,
  type FeedbackSort,
  type FeedbackStatus,
  type FeedbackUrgency,
} from "./types";
import { UrgencyPill, UrgencyToggle } from "./urgency";
import { BlockedNotice } from "../forum/BlockedNotice";
import { FavoriteStar } from "../forum/FavoriteStar";

function isModerator(user: { is_operator: boolean; role: string } | null): boolean {
  return Boolean(
    user && (user.is_operator || user.role === "moderator" || user.role === "community_admin"),
  );
}

function authorLine(post: FeedbackPost): string {
  const a = post.author;
  return `${a.display_name}${a.account_number ? ` · ${a.account_number}` : ""}`;
}

/* -- the board doors ------------------------------------------------------------- */

/** The board routes are doors, not pages. Since sheet row 103
 *  (2026-11-18) the boards live only inside Help & Support —
 *  the separate Feedback page and its menu item are gone
 *  (Ryan: Help carries all of it, with more besides) — so each
 *  door redirects into Help at its board's tab, and the links
 *  the dashboard widgets, the forum's system boards, the
 *  Roadmap page and the side panel already carry keep landing
 *  on the right board. */
export function BugBoardRedirect() {
  return <Navigate to="/help#bugs" replace />;
}

export function FeatureBoardRedirect() {
  return <Navigate to="/help#features" replace />;
}

/** The /feedback address itself (the deleted page's home):
 *  lands on Help's bug board tab, the deleted page's default. */
export function FeedbackHomeRedirect() {
  return <Navigate to="/help#bugs" replace />;
}

/** The sign-in door a signed-out visitor meets on the boards
 *  (owner 2026-11-10): the site's standing registered-only
 *  pattern — an honest explanation plus one button that goes
 *  to /login carrying the full destination, so signing in
 *  lands the visitor right back where they were headed
 *  (LoginPage reads location.state.from). No board content,
 *  counts or titles render behind it: the API refuses
 *  anonymous reads server-side, and the pages never ask. */
export function BoardsSignInDoor() {
  const t = useT();
  const location = useLocation();
  const from = location.pathname + location.search + location.hash;
  return (
    <Panel>
      <EmptyState
        title={t("feedback.door.title")}
        description={t("feedback.door.body")}
        action={
          <LinkButton to="/login" state={{ from }}>
            {t("feedback.door.signIn")}
          </LinkButton>
        }
      />
    </Panel>
  );
}

/** The board's body — post form, filter, true list — as ONE
 *  shared piece (Help & Support build, 2026-11-02): the board's
 *  own page and the Help & Support page's Report a bug /
 *  Request a feature tabs render THIS component, so posting
 *  from either place is the same act on the same members'
 *  board and the two can never drift apart. The boards
 *  themselves are permanent fixtures of the forum (their rows
 *  live in the forum's board list); this body is their engine
 *  room, and a single post's conversation still lives on its
 *  own page. A signed-out seat gets the sign-in door here too,
 *  so EVERY assembly of this body (Feedback page, Help &
 *  Support tabs) is members-only reading (2026-11-10). */
export function BoardBody({ board }: { board: FeedbackBoard }) {
  const { user, loading } = useAuth();
  const { toast } = useToast();
  const t = useT();
  const [searchParams] = useSearchParams();
  const [posts, setPosts] = useState<FeedbackPost[] | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState<FeedbackSort>("new");
  const [mineOnly, setMineOnly] = useState(false);
  const [error, setError] = useState("");
  /* A pre-filled start (owner order 2026-11-12): a door that
   * sends a member here with an ask already begun — the
   * Wallpaper tab's "Request a wallpaper design" — carries
   * ?title= / ?body=, and THIS form (Feature Requests only)
   * opens with them as its starting text. They are ordinary
   * initial state: fully editable, and what posts is an
   * ordinary board post, indistinguishable from a hand-typed
   * one. Read once, on mount; nothing re-applies them. */
  const [title, setTitle] = useState(() =>
    board === "feature" ? (searchParams.get("title") ?? "").slice(0, 300) : "",
  );
  const [body, setBody] = useState(() =>
    board === "feature" ? (searchParams.get("body") ?? "").slice(0, 20000) : "",
  );
  const [urgency, setUrgency] = useState<FeedbackUrgency>("medium");
  const [posting, setPosting] = useState(false);

  const load = useCallback(async () => {
    if (!user) return; // anonymous seats render the door; never ask
    try {
      const rows = mineOnly
        ? await getMine(board, sortBy)
        : await getBoard(board, true, statusFilter, sortBy);
      setPosts(rows);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("feedback.form.loadFailed"));
    }
  }, [board, user, statusFilter, mineOnly, sortBy]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner />;
  if (!user) return <BoardsSignInDoor />;

  async function onPost(e: FormEvent) {
    e.preventDefault();
    setPosting(true);
    try {
      const created = await createPost({
        board,
        title: title.trim(),
        body: body.trim(),
        urgency,
      });
      setTitle("");
      setBody("");
      setUrgency("medium");
      toast(
        created.visibility === "held"
          ? t("feedback.form.postHeld")
          : t("feedback.form.postThanks"),
        { tone: "success" },
      );
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.form.postFailed"), {
        title: t("feedback.form.errorTitle"),
        tone: "danger",
      });
    } finally {
      setPosting(false);
    }
  }

  async function onVote(post: FeedbackPost) {
    try {
      const updated = await toggleVote(post.id);
      setPosts((prev) =>
        (prev ?? []).map((p) => (p.id === updated.id ? updated : p)),
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.form.voteFailed"), {
        tone: "danger",
      });
    }
  }

  const visible = (posts ?? []).filter(
    (p) => p.visibility === "visible" || p.visibility === "held",
  );

  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      {user && <BlockedNotice feature="feedback_boards" />}

      {/* The filing form rides ON TOP of the list (owner,
          2026-11-10): "I don't want the form at the bottom of
          those pages." Because BoardBody is shared, the Help &
          Support board tabs carry the same arrangement. */}
      <Panel
        title={board === "bug" ? t("feedback.form.reportBug") : t("feedback.form.requestFeature")}
        className="tv-fb-compose-panel"
      >
        {user ? (
          <form
            onSubmit={onPost}
            className="tv-fb-compose"
            style={{ display: "grid", gap: "0.55rem" }}
          >
            <FormField label={t("feedback.form.title")} htmlFor={`fb-new-title-${board}`} required>
              <TextInput
                id={`fb-new-title-${board}`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={300}
                required
              />
            </FormField>
            <FormField label={t("feedback.form.details")} htmlFor={`fb-new-body-${board}`} required>
              <TextArea
                id={`fb-new-body-${board}`}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={5}
                maxLength={20000}
                required
              />
            </FormField>
            {/* The filer's urgency call (owner 2026-11-06):
                the 3-position toggle, defaulting to Medium.
                This is the ONLY place a filer ever sets it —
                after posting it locks, and only the people
                who respond on the boards can move it. */}
            <FormField
              label={t("feedback.list.col.urgency")}
              hint={t("feedback.form.urgencyHint")}
            >
              <UrgencyToggle
                value={urgency}
                onChange={setUrgency}
                label={t("feedback.list.col.urgency")}
              />
            </FormField>
            <div>
              <Button type="submit" loading={posting}>
                {t("feedback.form.post")}
              </Button>
            </div>
          </form>
        ) : (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            <Link to="/login">{t("feedback.door.signIn")}</Link>
            {t("feedback.form.signInTail")}
          </p>
        )}
      </Panel>

      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "end" }}>
        <FormField label={t("feedback.list.col.status")} htmlFor={`fb-filter-${board}`}>
          <Select
            id={`fb-filter-${board}`}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">{t("feedback.form.allStatuses")}</option>
            {(Object.keys(STATUS_LABELS) as FeedbackStatus[]).map((st) => (
              <option key={st} value={st}>
                {t(STATUS_LABEL_KEYS[st] as DictKey)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={t("feedback.sort.label")} htmlFor={`fb-sort-${board}`}>
          <Select
            id={`fb-sort-${board}`}
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as FeedbackSort)}
          >
            <option value="new">{t("feedback.sort.newest")}</option>
            <option value="top">{t("feedback.sort.top")}</option>
          </Select>
        </FormField>
        {user && (
          <Button
            type="button"
            variant={mineOnly ? "primary" : "secondary"}
            onClick={() => setMineOnly((v) => !v)}
          >
            {t("feedback.form.myPosts")}
          </Button>
        )}
      </div>

      {posts === null ? (
        <Spinner />
      ) : visible.length === 0 ? (
        <EmptyState
          title={t("feedback.empty.title")}
          description={
            mineOnly
              ? t("feedback.empty.mine")
              : statusFilter
                ? t("feedback.empty.filter")
                : t("feedback.empty.first")
          }
        />
      ) : (
        /* The board LIST (list-standard Wave 5, 2026-11-02): a
           true list — one post per ROW under a header row, facts
           in their own columns (post / type / status / author /
           date / comments / votes), on the dealer directory's
           CSS-grid role=table pattern. The body excerpt leaves
           the row: the full text lives on the post detail page,
           where it already rendered. The vote control stays in
           the row, working exactly as it did in the panel.
           Tighten (2026-11-09): the vote control is the row's
           own compact .tv-fb-vote — a fixed footprint whose
           voted state is fill alone (the shared Button's
           primary plate grew ~40px wider when voted and
           extended the row's edge) — and the author cell
           renders name + account number as a stacked-compact
           byline, identical on every row (see feedback.css).
           Main list layout (MLL lane #8, 2026-11-13): the table
           composes the shared .tv-inv-list frame + the scoped
           .tv-fb-mlist geometry in feedback.css, and the fact
           cells carry phone-only .tv-fb-mlabel words (the heads'
           own dictionary strings) for the ≤640px restack fold.
           Every column, fact and control is unchanged. */
        <div className="tv-fb-table tv-inv-list tv-fb-mlist" role="table">
          <div className="tv-fb-thead" role="row">
            <span role="columnheader">{t("feedback.list.col.post")}</span>
            <span role="columnheader">{t("feedback.list.col.type")}</span>
            <span role="columnheader">{t("feedback.list.col.status")}</span>
            <span role="columnheader">{t("feedback.list.col.urgency")}</span>
            <span role="columnheader">{t("feedback.list.col.author")}</span>
            <span role="columnheader">{t("feedback.list.col.date")}</span>
            <span role="columnheader">{t("feedback.list.col.comments")}</span>
            <span role="columnheader">{t("feedback.list.col.votes")}</span>
          </div>
          {visible.map((post) => (
            <div className="tv-fb-row" role="row" key={post.id}>
              <div className="tv-fb-cell-title" role="cell">
                <Link to={`/feedback/post/${post.id}`}>{post.title}</Link>
                {post.visibility === "held" && (
                  <Badge tone="warning">{t("feedback.held")}</Badge>
                )}
                {post.closed && (
                  <Badge tone="neutral">{t("feedback.closed")}</Badge>
                )}
              </div>
              <div className="tv-fb-cell-type" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.type")}</span>
                {post.board === "bug"
                  ? t("feedback.list.type.bug")
                  : t("feedback.list.type.feature")}
              </div>
              <div className="tv-fb-cell-status" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.status")}</span>
                <Badge tone={STATUS_TONES[post.status]}>
                  {t(STATUS_LABEL_KEYS[post.status] as DictKey)}
                </Badge>
              </div>
              <div className="tv-fb-cell-urgency" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.urgency")}</span>
                <UrgencyPill urgency={post.urgency} />
              </div>
              <div className="tv-fb-cell-author" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.author")}</span>
                <span className="tv-fb-cell-author-name">
                  {post.author.display_name}
                </span>
                {post.author.account_number && (
                  <span className="tv-fb-cell-author-num">
                    · {post.author.account_number}
                  </span>
                )}
              </div>
              <div className="tv-fb-cell-date" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.date")}</span>
                {new Date(post.created_at).toLocaleDateString()}
              </div>
              <div className="tv-fb-cell-comments" role="cell">
                <span className="tv-fb-mlabel">{t("feedback.list.col.comments")}</span>
                {post.comment_count}
              </div>
              <div className="tv-fb-cell-votes" role="cell">
                {user ? (
                  <button
                    type="button"
                    className="tv-fb-vote"
                    aria-pressed={post.voted_by_me}
                    aria-label={`${t("feedback.list.col.votes")}: ${post.vote_count}`}
                    onClick={() => void onVote(post)}
                  >
                    ▲ {post.vote_count}
                  </button>
                ) : (
                  <span className="tv-fb-vote tv-fb-vote--static">
                    ▲ {post.vote_count}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

    </>
  );
}

/* -- one post ------------------------------------------------------------------------ */

export function PostDetailPage() {
  const t = useT();
  const { postId } = useParams<{ postId: string }>();
  const { user, loading } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FeedbackPostDetail | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [commenting, setCommenting] = useState(false);
  const [status, setStatus] = useState<FeedbackStatus>("open");
  const [statusNote, setStatusNote] = useState("");
  const [flagTarget, setFlagTarget] = useState<{
    kind: "post" | "comment";
    id: string;
  } | null>(null);
  const [flagReason, setFlagReason] = useState("");
  const [flagBusy, setFlagBusy] = useState(false);
  const mod = isModerator(user);

  const load = useCallback(async () => {
    if (!postId || !user) return; // anonymous seats render the door
    try {
      const data = await getPost(postId, true);
      setDetail(data);
      setStatus(data.status);
      setStatusNote(data.status_note);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("feedback.post.loadFailed"));
    }
  }, [postId, user]);

  useEffect(() => {
    void load();
  }, [load]);

  // Members-only reading (2026-11-10): a signed-out visitor
  // gets the door with this post's URL as the return path —
  // never the post, never the API's refusal as a bare error.
  if (!loading && !user) {
    return (
      <div className="tv-fb-narrow">
        <Breadcrumbs
          items={[
            { label: t("nav.feedback"), to: "/feedback" },
            { label: t("feedback.post.crumb") },
          ]}
        />
        <BoardsSignInDoor />
      </div>
    );
  }
  if (error) {
    return (
      <div className="tv-fb-narrow">
        <Breadcrumbs
          items={[
            { label: t("nav.feedback"), to: "/feedback" },
            { label: t("feedback.post.crumb") },
          ]}
        />
        <Alert tone="danger">{error}</Alert>
      </div>
    );
  }
  if (!detail) return <Spinner />;

  const removed = detail.visibility === "removed_author" || detail.visibility === "removed_mod";

  async function onVote() {
    try {
      const updated = await toggleVote(detail!.id);
      setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.form.voteFailed"), { tone: "danger" });
    }
  }

  async function onComment(e: FormEvent) {
    e.preventDefault();
    setCommenting(true);
    try {
      await createComment(detail!.id, draft.trim());
      setDraft("");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.post.commentFailed"), {
        tone: "danger",
      });
    } finally {
      setCommenting(false);
    }
  }

  // Flagging (admin lane, 2026-11-07): a real form with a
  // notes field — why: spam, stolen property, abuse, other —
  // replacing the old window.prompt. The flag notifies the
  // whole moderation team server-side.
  async function onSendFlag() {
    if (!flagTarget || flagBusy) return;
    setFlagBusy(true);
    try {
      await reportTarget({
        target_kind: flagTarget.kind,
        target_id: flagTarget.id,
        reason: flagReason.trim(),
      });
      setFlagTarget(null);
      setFlagReason("");
      toast(t("feedback.post.flagDone"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.post.flagFailed"), {
        tone: "danger",
      });
    } finally {
      setFlagBusy(false);
    }
  }

  async function onDeletePost() {
    if (!window.confirm(t("feedback.post.removeConfirm"))) return;
    try {
      await deletePost(detail!.id);
      navigate(detail!.board === "bug" ? "/feedback#bugs" : "/feedback#features");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.post.removeFailed"), {
        tone: "danger",
      });
    }
  }

  async function onSaveStatus(e: FormEvent) {
    e.preventDefault();
    try {
      const updated = await setPostStatus(detail!.id, status, statusNote.trim());
      setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
      toast(t("feedback.post.statusSaved"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.post.statusFailed"), {
        tone: "danger",
      });
    }
  }

  async function onUrgency(next: FeedbackUrgency) {
    try {
      const updated = await setPostUrgency(detail!.id, next);
      setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
      toast(t("feedback.post.urgencySaved"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("feedback.post.urgencyFailed"), {
        tone: "danger",
      });
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "var(--max-content-width)" }}>
      <Breadcrumbs
        items={[
          { label: "Feedback", to: "/feedback" },
          {
            label: detail.board === "bug" ? t("feedback.tab.bugs") : t("feedback.tab.features"),
            to: detail.board === "bug" ? "/feedback#bugs" : "/feedback#features",
          },
          { label: detail.title || t("feedback.post.crumb") },
        ]}
      />
      {user && <BlockedNotice feature="feedback_boards" />}
      <Panel>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "0.6rem",
              alignItems: "baseline",
              flexWrap: "wrap",
            }}
          >
            <h1 style={{ margin: 0, fontSize: "1.3rem" }}>{detail.title}</h1>
            <span className="tv-post-head-actions">
              <FavoriteStar kind="post" targetId={detail.id} signedIn={!!user} />
              <UrgencyPill urgency={detail.urgency} />
              <Badge tone={STATUS_TONES[detail.status]}>
                {t(STATUS_LABEL_KEYS[detail.status] as DictKey)}
              </Badge>
              {detail.closed && (
                <Badge tone="neutral">{t("feedback.closed")}</Badge>
              )}
            </span>
          </div>
          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {authorLine(detail)} · {new Date(detail.created_at).toLocaleDateString()}
          </span>
          {detail.status_note && (
            <Alert tone="info">
              {t("feedback.post.teamNote").replace("{note}", detail.status_note)}
            </Alert>
          )}
          {removed ? (
            <Alert tone="warning">
              {detail.visibility === "removed_mod"
                ? t("feedback.post.removedByMod")
                : t("feedback.post.removedByAuthor")}
            </Alert>
          ) : (
            <p style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {detail.body}
            </p>
          )}
          {!removed && (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {user ? (
                <Button
                  type="button"
                  size="sm"
                  variant={detail.voted_by_me ? "primary" : "secondary"}
                  onClick={() => void onVote()}
                >
                  ▲ {detail.vote_count}
                </Button>
              ) : (
                <span>▲ {detail.vote_count}</span>
              )}
              {user && !detail.mine && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setFlagReason("");
                    setFlagTarget({ kind: "post", id: detail.id });
                  }}
                >
                  {t("feedback.post.flag")}
                </Button>
              )}
              {user && detail.mine && (
                <Button type="button" size="sm" variant="ghost" onClick={() => void onDeletePost()}>
                  {t("feedback.post.removeMine")}
                </Button>
              )}
            </div>
          )}
        </div>
      </Panel>

      {mod && !removed && (
        <Panel title={t("feedback.post.modTools")}>
          {/* The urgency lever (owner 2026-11-06): the filer
              set it once at posting and can't touch it again;
              the responders can. It saves the moment it's
              picked — a toggle, not a form. */}
          <div className="tv-fb-mod-urgency">
            <FormField
              label={t("feedback.post.modUrgencyLabel")}
              hint={t("feedback.post.modUrgencyHint")}
            >
              <UrgencyToggle
                value={detail.urgency}
                onChange={(next) => void onUrgency(next)}
                label={t("feedback.post.modUrgencyLabel")}
              />
            </FormField>
          </div>
          <form onSubmit={onSaveStatus} style={{ display: "grid", gap: "var(--space-3)" }}>
            <FormField label={t("feedback.post.statusLabel")} htmlFor="fb-status">
              <Select
                id="fb-status"
                value={status}
                onChange={(e) => setStatus(e.target.value as FeedbackStatus)}
              >
                {(Object.keys(STATUS_LABELS) as FeedbackStatus[]).map((st) => (
                  <option key={st} value={st}>
                    {t(STATUS_LABEL_KEYS[st] as DictKey)}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("feedback.post.statusNoteLabel")} htmlFor="fb-status-note">
              <TextInput
                id="fb-status-note"
                value={statusNote}
                onChange={(e) => setStatusNote(e.target.value)}
                maxLength={500}
              />
            </FormField>
            <div>
              <Button type="submit">{t("feedback.post.saveStatus")}</Button>
            </div>
          </form>
        </Panel>
      )}

      <Panel title={t("feedback.post.commentsTitle").replace("{count}", String(detail.comments.length))}>
        <div style={{ display: "grid", gap: "0.8rem" }}>
          {detail.comments.length === 0 && (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>{t("feedback.post.noComments")}</p>
          )}
          {detail.comments.map((comment) => {
            const commentRemoved =
              comment.visibility === "removed_author" || comment.visibility === "removed_mod";
            return (
              <div
                key={comment.id}
                style={{
                  borderTop: "1px solid var(--edge)",
                  paddingTop: "0.6rem",
                  display: "grid",
                  gap: "0.3rem",
                }}
              >
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  {comment.author.display_name}
                  {comment.author.account_number
                    ? ` · ${comment.author.account_number}`
                    : ""}{" "}
                  · {new Date(comment.created_at).toLocaleDateString()}
                  {comment.visibility === "held" && (
                    <>
                      {" "}
                      <Badge tone="warning">{t("feedback.held")}</Badge>
                    </>
                  )}
                </span>
                {commentRemoved ? (
                  <span style={{ color: "var(--text-muted)" }}>
                    <em>{t("feedback.post.commentRemoved")}</em>
                  </span>
                ) : (
                  <p style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                    {comment.body}
                  </p>
                )}
                {user && !commentRemoved && (
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    {!comment.mine && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setFlagReason("");
                          setFlagTarget({ kind: "comment", id: comment.id });
                        }}
                      >
                        {t("feedback.post.flag")}
                      </Button>
                    )}
                    {comment.mine && (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          try {
                            await deleteComment(comment.id);
                            await load();
                          } catch (err) {
                            toast(
                              err instanceof ApiError
                                ? err.message
                                : t("feedback.post.removeFailed"),
                              { tone: "danger" },
                            );
                          }
                        }}
                      >
                        {t("feedback.post.removeBtn")}
                      </Button>
                    )}
                  </span>
                )}
              </div>
            );
          })}
          {detail.closed && !removed ? (
            /* Closed posts take no new comments (sweep E5): the
               thread above stays readable and this notice, in
               plain words, stands where the form stood. The
               server refuses comment writes on closed posts too
               — this is the visible half of the same lock. */
            <Alert tone="info">{t("feedback.post.closedNotice")}</Alert>
          ) : user && !removed ? (
            <form onSubmit={onComment} style={{ display: "grid", gap: "var(--space-3)" }}>
              <FormField label={t("feedback.post.addComment")} htmlFor="fb-comment">
                <TextArea
                  id="fb-comment"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={3}
                  maxLength={10000}
                  required
                />
              </FormField>
              <div>
                <Button type="submit" loading={commenting}>
                  {t("feedback.post.commentBtn")}
                </Button>
              </div>
            </form>
          ) : (
            !user && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                <Link to="/login">{t("feedback.door.signIn")}</Link>
                {t("feedback.post.signInToComment")}
              </p>
            )
          )}
        </div>
      </Panel>
      <Modal
        open={flagTarget !== null}
        onClose={() => setFlagTarget(null)}
        title={
          flagTarget?.kind === "comment"
            ? t("feedback.post.flagCommentTitle")
            : t("feedback.post.flagPostTitle")
        }
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setFlagTarget(null)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={() => void onSendFlag()} disabled={flagBusy}>
              {t("feedback.post.sendFlag")}
            </Button>
          </>
        }
      >
        <FormField label={t("feedback.post.flagLabel")} htmlFor="fb-flag-reason">
          <TextArea
            id="fb-flag-reason"
            rows={3}
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
            maxLength={500}
            placeholder={t("feedback.post.flagPlaceholder")}
          />
        </FormField>
      </Modal>
    </div>
  );
}
