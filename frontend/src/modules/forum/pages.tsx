/** Community Forum — categories, threads, posts.
 *
 *  Reading is PUBLIC: these pages render for signed-out visitors
 *  through the /forum/public/* twins with the exact same payloads
 *  (no emails anywhere; authors show the public profile fields).
 *  Writing rides the API's gates — the paid-contribution gate's
 *  refusal renders as a friendly note under the composer, never
 *  a silent failure.
 *
 *  Replies are FLAT with one-quote snapshots: the quote is copied
 *  onto the reply, so it reads correctly even if the original is
 *  later edited or removed. A post may attach ONE community
 *  reference (a Community Part or a Tools For Sale listing),
 *  rendered as a live card; a dead reference renders an honest
 *  "no longer available" card. */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import "./forum.css";
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  EmptyState,
  FormField,
  Panel,
  SectionPageHeader,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  type SectionPageFact,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { SellerPrice } from "../../components/SellerPrice";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/money";
import { useAuth } from "../core";
import { useMyModules } from "../core/MyModules";
import { BlockedNotice } from "./BlockedNotice";
import { FavoriteStar } from "./FavoriteStar";
import { getBoard, getPublicBoard } from "../marketplace/api";
import { reputationBadge } from "../marketplace/types";
import { listCommunity, listCommunityPublic } from "../parts/api";
import {
  createCategory,
  createReply,
  createThread,
  deleteForumThread,
  deletePost,
  editPost,
  getAdminCategories,
  getCategories,
  getMyThreads,
  getThread,
  getThreads,
  reportPost,
  searchThreads,
  updateCategory,
  type LinkRef,
} from "./api";
import type {
  ForumAuthor,
  ForumCategory,
  ForumPost,
  ForumThread,
  ForumThreadDetail,
} from "./types";

function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

/** The author block on every post: display name (linking to the
 *  public profile), account number, member since, the reputation
 *  badge from the ONE aggregate, and a role badge for staff. */
export function AuthorLine({ author }: { author: ForumAuthor }) {
  const former = author.display_name === "Former member";
  return (
    <span style={{ display: "inline-flex", gap: "0.45rem", flexWrap: "wrap", alignItems: "baseline" }}>
      {former ? (
        <strong>Former member</strong>
      ) : (
        <Link to={`/users/${author.user_id}`}>
          <strong>{author.display_name}</strong>
        </Link>
      )}
      {!former && author.account_number && (
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {author.account_number}
        </span>
      )}
      {!former && author.member_since && (
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          Member since {formatDate(author.member_since)}
        </span>
      )}
      {!former && (
        <span title="Seller rating" style={{ fontSize: "0.9rem" }}>
          {reputationBadge(author.reputation)}
        </span>
      )}
      {author.role === "moderator" && <Badge tone="accent">Moderator</Badge>}
      {author.role === "community_admin" && <Badge tone="accent">Community admin</Badge>}
    </span>
  );
}

export function LinkCardView({ post }: { post: ForumPost }) {
  const link = post.link;
  if (!link) return null;
  if (!link.available) {
    return (
      <Panel>
        <span style={{ color: "var(--text-muted)" }}>
          <strong>{link.title}</strong> — this{" "}
          {link.type === "listing" ? "listing" : "part"} is no longer available.
        </span>
      </Panel>
    );
  }
  const href = link.type === "listing" ? `/marketplace/${link.id}` : `/parts/community`;
  return (
    <Panel>
      <div style={{ display: "flex", gap: "0.8rem", alignItems: "center" }}>
        {link.photo_url && (
          <img
            src={link.photo_url}
            alt=""
            style={{
              width: "72px",
              height: "72px",
              objectFit: "cover",
              borderRadius: "var(--radius)",
              border: "1px solid var(--edge)",
            }}
          />
        )}
        <div style={{ display: "grid", gap: "0.2rem" }}>
          <Badge tone="neutral">{link.type === "listing" ? "Tools for sale" : "Community Part"}</Badge>
          <Link to={href} style={{ fontWeight: 600 }}>
            {link.title}
          </Link>
          <span>
            {link.price !== null && link.price !== undefined ? (
              <SellerPrice amount={link.price} currency={link.seller_currency} />
            ) : (
              "Make offer"
            )}
          </span>
        </div>
      </div>
    </Panel>
  );
}

/** The ONE-reference picker: pick a kind, search the live public
 *  surfaces, choose. Server re-validates at post time. */
export function LinkPicker({
  value,
  onChange,
  signedIn,
}: {
  value: LinkRef;
  onChange: (next: LinkRef) => void;
  signedIn: boolean;
}) {
  const [options, setOptions] = useState<
    { id: string; title: string; price: string | null; currency: string }[]
  >([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  // Parked-module signs (owner directive, 2026-10-31): a
  // reference kind is offered only while its module is
  // effective for the viewer — listings ride marketplace,
  // community parts ride parts — and with both off the
  // picker stands down entirely. Each returns on its own
  // when its module is unparked.
  const { has } = useMyModules();
  const listingOn = has("marketplace");
  const partOn = has("parts");

  useEffect(() => {
    if (!value.link_type) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const load =
      value.link_type === "listing"
        ? (signedIn ? getBoard({ q: query }) : getPublicBoard({ q: query })).then((rows) =>
            rows.map((r) => ({
              id: r.id,
              title: r.title,
              price: r.price === null ? null : String(r.price),
              currency: r.seller_currency,
            })),
          )
        : (signedIn ? listCommunity({ q: query }) : listCommunityPublic({ q: query })).then(
            (rows) =>
              rows.map((r) => ({
                id: r.id,
                title: r.title,
                price: r.asking_price === null ? null : String(r.asking_price),
                currency: r.seller_currency,
              })),
          );
    load
      .then((rows) => {
        if (!cancelled) setOptions(rows.slice(0, 25));
      })
      .catch(() => {
        if (!cancelled) setOptions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [value.link_type, query, signedIn]);

  if (!listingOn && !partOn) return null;

  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      <FormField label="Attach a community reference (optional)">
        <Select
          value={value.link_type}
          onChange={(e) =>
            onChange({
              link_type: e.target.value as LinkRef["link_type"],
              link_id: null,
            })
          }
        >
          <option value="">Nothing attached</option>
          {listingOn && (
            <option value="listing">A Tools for sale listing</option>
          )}
          {partOn && <option value="part">A Community Part</option>}
        </Select>
      </FormField>
      {value.link_type && (
        <>
          <FormField label="Search">
            <TextInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type to search the live listings…"
            />
          </FormField>
          <FormField label={value.link_type === "listing" ? "Listing" : "Part"}>
            <Select
              value={value.link_id ?? ""}
              onChange={(e) => onChange({ ...value, link_id: e.target.value || null })}
            >
              <option value="">{loading ? "Loading…" : "Choose one…"}</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.title}
                  {option.price !== null
                    ? ` — ${formatMoney(option.price, option.currency)}`
                    : ""}
                </option>
              ))}
            </Select>
          </FormField>
        </>
      )}
    </div>
  );
}

/** The paid-gate / module-gate refusal rendered as a friendly
 *  note: the server message verbatim (it already explains). */
function GateNote({ error }: { error: ApiError }) {
  return <Alert tone="warning">{error.message}</Alert>;
}

function isGateError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.code === "paid_plan_required" || error.code === "module_unavailable")
  );
}

/* ------------------------------------------------------------------ */
/* Forum home: the room index + search + my threads                    */
/*                                                                     */
/* REMAKE (Sweep C4, 2026-11-12): the front page is rebuilt out of     */
/* the family's own parts — the Feedback page's SectionPageHeader      */
/* (plate, title, subtitle, facts) over ONE true-list room index       */
/* in the topic list's table family. What the old page did that        */
/* this one deliberately does not:                                     */
/*  - The Bug Reports / Feature Requests boards are NOT rooms          */
/*    here. They keep their home on the Feedback page; this page       */
/*    carries ONE plain labelled door to them, below the list.         */
/*    (Their rows still arrive in the categories payload — the          */
/*    backend ranks them first for every consumer — so the page        */
/*    filters exactly those two system keys out of its own list;       */
/*    no other consumer changes.)                                      */
/*  - No "Built-in" badge/bar: the mark explained nothing a             */
/*    reader could act on, on any row that carried it.                 */
/*  - No second furniture for empty rooms: an empty room is a          */
/*    row whose Latest cell says so in words.                          */
/* Search results and My threads render through ThreadTable, the       */
/* topic list itself — one list treatment for every thread list        */
/* on the forum's surfaces.                                            */
/* ------------------------------------------------------------------ */

/** The two permanent boards' system keys — the rows the front
 *  page must never present as forum rooms (see boardPathFor). */
function isBoardCategory(category: ForumCategory): boolean {
  return boardPathFor(category.system_key) !== null;
}

/** The room index: one room per row under a header row — room
 *  (name door + the "what belongs here" line), threads, posts,
 *  and the latest thread (its own door into the thread page)
 *  with its date. An empty room's Latest cell directs in words,
 *  the family empty-state habit at row scale. */
function RoomTable({ rooms }: { rooms: ForumCategory[] }) {
  const t = useT();
  return (
    <div className="tv-forum-table" role="table">
      <div className="tv-forum-thead" role="row">
        <span role="columnheader">{t("forum.list.col.room")}</span>
        <span role="columnheader">{t("forum.list.col.threads")}</span>
        <span role="columnheader">{t("forum.list.col.posts")}</span>
        <span role="columnheader">{t("forum.list.col.latest")}</span>
      </div>
      {rooms.map((category) => (
        <div className="tv-forum-row" role="row" key={category.id}>
          <div className="tv-forum-cell-room" role="cell">
            <Link
              className="tv-forum-room-name"
              to={`/forum/category/${category.id}`}
            >
              {category.name}
            </Link>
            {category.description && (
              <span className="tv-forum-room-desc">{category.description}</span>
            )}
          </div>
          <div role="cell">{category.thread_count}</div>
          <div role="cell">{category.post_count}</div>
          <div className="tv-forum-cell-latest" role="cell">
            {category.last_thread_id ? (
              <>
                <Link to={`/forum/thread/${category.last_thread_id}`}>
                  {category.last_thread_title}
                </Link>
                <span className="tv-forum-latest-date">
                  {formatDate(category.last_activity_at)}
                </span>
              </>
            ) : (
              <span className="tv-forum-empty-note">
                {t("forum.home.noThreadsYet")}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ForumPage() {
  const { user } = useAuth();
  const t = useT();
  const signedIn = !!user;
  const [categories, setCategories] = useState<ForumCategory[] | null>(null);
  const [mine, setMine] = useState<ForumThread[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ForumThread[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getCategories(signedIn)
      .then(setCategories)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : t("forum.home.loadFailed")),
      );
    if (signedIn) {
      getMyThreads()
        .then(setMine)
        .catch(() => setMine([]));
    }
    // t is stable per locale; the load keys on the seat only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn]);

  const runSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) {
      setResults(null);
      return;
    }
    try {
      setResults(await searchThreads(query.trim(), signedIn));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("forum.home.searchFailed"));
    }
  };

  // The forum's own rooms only — the two boards are filtered
  // out of the index AND the header facts (they are not forum
  // rooms, and their counts are the Feedback boards' posts).
  const rooms = (categories ?? []).filter((c) => !isBoardCategory(c));
  const facts: SectionPageFact[] | undefined =
    categories === null
      ? undefined
      : [
          { label: t("forum.home.fact.rooms"), value: rooms.length },
          {
            label: t("forum.home.fact.threads"),
            value: rooms.reduce((sum, c) => sum + c.thread_count, 0),
          },
        ];

  return (
    <div className="tv-stack">
      <SectionPageHeader
        thumb={<ArtIcon name="forum" size={96} />}
        title={t("nav.forum")}
        subtitle={t("forum.home.subtitle")}
        facts={facts}
      />
      {signedIn && <BlockedNotice feature="forums" />}
      {error && <Alert tone="danger">{error}</Alert>}
      <form onSubmit={runSearch} style={{ display: "flex", gap: "0.5rem" }}>
        <TextInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("forum.home.searchPlaceholder")}
          aria-label={t("forum.home.searchLabel")}
        />
        <Button type="submit" variant="secondary">
          {t("forum.home.searchButton")}
        </Button>
      </form>
      {results !== null &&
        (results.length === 0 ? (
          <EmptyState
            title={t("forum.home.noMatchesTitle")}
            description={t("forum.home.noMatches")}
          />
        ) : (
          <ThreadTable threads={results} />
        ))}
      {categories === null && !error ? (
        <Spinner />
      ) : categories !== null && rooms.length === 0 ? (
        <EmptyState
          title={t("forum.home.noRoomsTitle")}
          description={t("forum.home.noRooms")}
        />
      ) : categories !== null ? (
        <RoomTable rooms={rooms} />
      ) : null}
      {/* The boards' one door: plain, labelled, once. The boards
          themselves — filing, statuses, votes — live on the
          Feedback page and nowhere else. */}
      <Panel title={t("forum.home.boardsDoor.title")}>
        <p style={{ marginTop: 0 }}>{t("forum.home.boardsDoor.body")}</p>
        <Link to="/feedback">{t("forum.home.boardsDoor.link")}</Link>
      </Panel>
      {signedIn && mine.length > 0 && (
        <Panel title={t("forum.home.myThreads")}>
          <ThreadTable threads={mine} />
        </Panel>
      )}
      {!signedIn && (
        <Alert tone="info">
          {t("forum.home.guest.lead")}
          <Link to="/login">{t("forum.home.guest.login")}</Link>
          {t("forum.home.guest.mid")}
          <Link to="/signup">{t("forum.home.guest.signup")}</Link>
          {t("forum.home.guest.tail")}
        </Alert>
      )}
      {user?.is_operator && <CategoryAdmin />}
    </div>
  );
}

/** Operator furniture: the rooms themselves. Create, rename,
 *  reorder, archive (a flag — history is never orphaned) and
 *  restore categories. Operators only; the API enforces it. */
function CategoryAdmin() {
  const { toast } = useToast();
  const [rows, setRows] = useState<ForumCategory[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sortOrder, setSortOrder] = useState("60");
  const [busy, setBusy] = useState(false);
  const [adminError, setAdminError] = useState("");

  const load = useCallback(async () => {
    try {
      setRows(await getAdminCategories());
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "Categories couldn't be loaded.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setAdminError("");
    try {
      await createCategory({
        name: name.trim(),
        description: description.trim(),
        sort_order: Number(sortOrder) || 0,
      });
      setName("");
      setDescription("");
      toast("Category created.");
      await load();
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "The category couldn't be created.");
    } finally {
      setBusy(false);
    }
  };

  const flipActive = async (row: ForumCategory) => {
    try {
      await updateCategory(row.id, { is_active: !row.is_active });
      toast(row.is_active ? "Category archived." : "Category restored.");
      await load();
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "That change failed.");
    }
  };

  const rename = async (row: ForumCategory) => {
    const next = window.prompt("Category name", row.name);
    if (!next || !next.trim() || next.trim() === row.name) return;
    try {
      await updateCategory(row.id, { name: next.trim() });
      await load();
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "The rename failed.");
    }
  };

  const editDescription = async (row: ForumCategory) => {
    const next = window.prompt(
      "Category description — the 'what belongs here' line under the room's name in the room lists",
      row.description,
    );
    if (next === null || next.trim() === row.description) return;
    try {
      await updateCategory(row.id, { description: next.trim() });
      toast("Description saved.");
      await load();
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "The description couldn't be saved.");
    }
  };

  return (
    <Panel>
      <h2 style={{ marginTop: 0 }}>Manage categories (operator)</h2>
      {adminError && <Alert tone="danger">{adminError}</Alert>}
      {rows === null ? (
        <Spinner />
      ) : (
        <div style={{ display: "grid", gap: "0.5rem", marginBottom: "1rem" }}>
          {rows.map((row) => (
            <div
              key={row.id}
              style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <strong>{row.name}</strong>
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                order {row.sort_order} · {row.thread_count} threads
                {row.description ? ` · ${row.description}` : ""}
              </span>
              {!row.is_active && <Badge tone="warning">Archived</Badge>}
              {boardPathFor(row.system_key) ? (
                /* The permanent boards (owner directive
                 * 2026-11-02): no rename, no archive — the
                 * controls simply don't exist for these rows,
                 * and the API refuses the calls too. */
                <Badge tone="accent">Permanent — built-in</Badge>
              ) : (
                <>
                  <Button variant="ghost" size="sm" onClick={() => void rename(row)}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => void editDescription(row)}>
                    Description
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => void flipActive(row)}>
                    {row.is_active ? "Archive" : "Restore"}
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <form onSubmit={create} style={{ display: "grid", gap: "0.6rem" }}>
        <FormField label="New category name">
          <TextInput value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </FormField>
        <FormField label="Description">
          <TextInput value={description} onChange={(e) => setDescription(e.target.value)} />
        </FormField>
        <FormField label="Sort order">
          <TextInput value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} inputMode="numeric" />
        </FormField>
        <div>
          <Button type="submit" disabled={busy}>
            Add category
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** The category thread LIST (list-standard Wave 5, 2026-11-02):
 *  a true list — one thread per ROW under a header row, facts in
 *  their own columns (thread / author / replies / last activity),
 *  on the dealer directory's CSS-grid role=table pattern. The
 *  excerpt leaves the row: the full opening post lives on the
 *  thread page, where it already rendered. Ordering (pinned
 *  first) and the pin/lock/held badges are exactly the payload's,
 *  unchanged. Since the Sweep C4 front-page remake (2026-11-12)
 *  this table is ALSO the front page's thread-list treatment —
 *  its search results and "My threads" render through here, and
 *  the old ThreadRow panel card is gone. The list carries no
 *  moderator controls today (thread deletion lives on the
 *  thread page), so none are lost. */
function ThreadTable({ threads }: { threads: ForumThread[] }) {
  const t = useT();
  return (
    <div className="tv-thread-table" role="table">
      <div className="tv-thread-thead" role="row">
        <span role="columnheader">{t("forum.list.col.thread")}</span>
        <span role="columnheader">{t("forum.list.col.author")}</span>
        <span role="columnheader">{t("forum.list.col.replies")}</span>
        <span role="columnheader">{t("forum.list.col.lastActivity")}</span>
      </div>
      {threads.map((thread) => (
        <div className="tv-thread-row" role="row" key={thread.id}>
          <div className="tv-thread-cell-title" role="cell">
            {thread.pinned && <Badge tone="accent">Pinned</Badge>}
            {thread.locked && <Badge tone="neutral">Locked</Badge>}
            {thread.held && <Badge tone="warning">Waiting for moderation</Badge>}
            <Link to={`/forum/thread/${thread.id}`}>{thread.title}</Link>
          </div>
          <div role="cell">
            <AuthorLine author={thread.author} />
          </div>
          <div role="cell">{thread.reply_count}</div>
          <div className="tv-thread-cell-last" role="cell">
            {formatDateTime(thread.last_post_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Category: thread list + new-thread composer                         */
/* ------------------------------------------------------------------ */

/** Where a permanent board's row sends you: the board's own
 *  page, where its posts live. Ordinary rooms return null. */
export function boardPathFor(systemKey: string | null): string | null {
  if (systemKey === "bug_reports") return "/feedback/bugs";
  if (systemKey === "feature_requests") return "/feedback/features";
  return null;
}

export function CategoryPage() {
  const { categoryId } = useParams<{ categoryId: string }>();
  const { user } = useAuth();
  const signedIn = !!user;
  const [category, setCategory] = useState<ForumCategory | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    getCategories(signedIn)
      .then((cats) => {
        if (!cancelled) {
          setCategory(cats.find((c) => c.id === categoryId) ?? null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "This category couldn't be loaded.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId, signedIn]);

  // A permanent board's posts live on the board's own page —
  // a category URL for one lands there, never on an empty
  // thread list pretending the board is quiet.
  const boardPath = category ? boardPathFor(category.system_key) : null;
  if (boardPath) return <Navigate to={boardPath} replace />;

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Breadcrumbs
        items={[
          { label: "Home", to: "/" },
          { label: "Community Forum", to: "/forum" },
          { label: category?.name ?? "Category" },
        ]}
      />
      <h1>{category?.name ?? "Category"}</h1>
      {category?.description && (
        <p style={{ color: "var(--text-muted)", marginTop: "-0.6rem" }}>{category.description}</p>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {categoryId && <RoomBody categoryId={categoryId} />}
    </div>
  );
}

/** A room's body — the new-thread composer + the thread list —
 *  as ONE shared piece (Help & Support build, 2026-11-02): the
 *  category page and the Help & Support page's Ask the
 *  community tab render THIS component for the room each
 *  shows, so asking from either place is the same act (same
 *  composer, same paid-plan gate note, same thread list) and
 *  the two can never drift apart. */
export function RoomBody({
  categoryId,
  emptyTitle,
  emptyDescription,
}: {
  categoryId: string;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const { user } = useAuth();
  const signedIn = !!user;
  const navigate = useNavigate();
  const { toast } = useToast();
  const [threads, setThreads] = useState<ForumThread[] | null>(null);
  const [error, setError] = useState("");
  const [showComposer, setShowComposer] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [link, setLink] = useState<LinkRef>({ link_type: "", link_id: null });
  const [posting, setPosting] = useState(false);
  const [gateError, setGateError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");

  const load = useCallback(async () => {
    try {
      setThreads(await getThreads(categoryId, signedIn));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This category couldn't be loaded.");
    }
  }, [categoryId, signedIn]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!categoryId) return;
    setPosting(true);
    setGateError(null);
    setFormError("");
    try {
      const thread = await createThread({
        category_id: categoryId,
        title: title.trim(),
        body: body.trim(),
        link_type: link.link_type,
        link_id: link.link_id,
      });
      if (thread.held) {
        toast("Your thread is waiting for moderation — it'll appear once it's released.");
        setShowComposer(false);
        await load();
      } else {
        navigate(`/forum/thread/${thread.id}`);
      }
    } catch (err) {
      if (isGateError(err)) setGateError(err);
      else setFormError(err instanceof ApiError ? err.message : "The thread couldn't be posted.");
    } finally {
      setPosting(false);
    }
  };

  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      {signedIn && !showComposer && (
        <div>
          <Button onClick={() => setShowComposer(true)}>Start a new thread</Button>
        </div>
      )}
      {!signedIn && (
        <Alert tone="info">
          <Link to="/login">Log in</Link> to start a thread — reading is open to everyone.
        </Alert>
      )}
      {showComposer && (
        <Panel>
          <form onSubmit={submit} style={{ display: "grid", gap: "0.75rem" }}>
            <h2 style={{ margin: 0 }}>New thread</h2>
            {gateError && <GateNote error={gateError} />}
            {formError && <Alert tone="danger">{formError}</Alert>}
            <FormField label="Title">
              <TextInput value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
            </FormField>
            <FormField label="Opening post">
              <TextArea value={body} onChange={(e) => setBody(e.target.value)} rows={6} />
            </FormField>
            <LinkPicker value={link} onChange={setLink} signedIn={signedIn} />
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <Button type="submit" disabled={posting}>
                {posting ? "Posting…" : "Post thread"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setShowComposer(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Panel>
      )}
      {threads === null && !error ? (
        <Spinner />
      ) : threads && threads.length === 0 ? (
        <EmptyState
          title={emptyTitle ?? "No threads yet"}
          description={emptyDescription ?? "This room is quiet — start the first conversation."}
        />
      ) : (
        <ThreadTable threads={threads ?? []} />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Thread: posts + reply composer                                      */
/* ------------------------------------------------------------------ */

function PostCard({
  post,
  signedIn,
  onChanged,
  onQuote,
}: {
  post: ForumPost;
  signedIn: boolean;
  onChanged: () => void;
  onQuote: (post: ForumPost) => void;
}) {
  const { user } = useAuth();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(post.body);
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const removed = post.status === "removed";
  const isMod =
    !!user && (user.is_operator || user.role === "moderator" || user.role === "community_admin");

  const saveEdit = async () => {
    setBusy(true);
    setActionError("");
    try {
      await editPost(post.id, draft.trim());
      setEditing(false);
      onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "The edit couldn't be saved.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deletePost(post.id);
      toast("Post removed.");
      onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "The post couldn't be removed.");
    } finally {
      setBusy(false);
    }
  };

  const sendReport = async () => {
    setBusy(true);
    setActionError("");
    try {
      await reportPost(post.id, reason.trim());
      setReporting(false);
      toast("Flagged — the moderation team will take a look.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "The report couldn't be sent.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel className="tv-forum-post">
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.6rem", flexWrap: "wrap" }}>
          <AuthorLine author={post.author} />
          <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            {formatDateTime(post.created_at)}
            {post.edited_at ? " · edited" : ""}
          </span>
        </div>
        {post.status === "held" && (
          <Alert tone="warning">
            This post is waiting for moderation — only you{isMod ? " and the moderators" : ""} can
            see it right now.
          </Alert>
        )}
        {removed ? (
          <p style={{ color: "var(--text-muted)", fontStyle: "italic", margin: 0 }}>
            {post.removed_by === "author"
              ? "This post was removed by its author."
              : "This post was removed by moderation."}
          </p>
        ) : editing ? (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} />
            {actionError && <Alert tone="danger">{actionError}</Alert>}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <Button onClick={saveEdit} disabled={busy}>
                Save changes
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            {post.quote && (
              <blockquote
                style={{
                  margin: 0,
                  padding: "0.5rem 0.75rem",
                  borderLeft: "3px solid var(--edge)",
                  color: "var(--text-muted)",
                }}
              >
                <strong>{post.quote.author_name}:</strong> {post.quote.excerpt}
              </blockquote>
            )}
            <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{post.body}</p>
            <LinkCardView post={post} />
          </>
        )}
        {!removed && signedIn && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {post.status === "visible" && (
              <Button variant="ghost" size="sm" onClick={() => onQuote(post)}>
                Quote
              </Button>
            )}
            {post.mine && post.status === "visible" && (
              <>
                <Button variant="ghost" size="sm" onClick={() => { setDraft(post.body); setEditing(true); }}>
                  Edit
                </Button>
                <Button variant="ghost" size="sm" onClick={remove} disabled={busy}>
                  Remove
                </Button>
              </>
            )}
            {!post.mine && post.status === "visible" && (
              <Button variant="ghost" size="sm" onClick={() => setReporting((v) => !v)}>
                Flag
              </Button>
            )}
          </div>
        )}
        {reporting && (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            <FormField label="Flag this post — what's wrong?">
              <TextInput
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                placeholder="Spam, stolen property, abuse, other…"
              />
            </FormField>
            {actionError && <Alert tone="danger">{actionError}</Alert>}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <Button onClick={sendReport} disabled={busy}>
                Send flag
              </Button>
              <Button variant="ghost" onClick={() => setReporting(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {!reporting && actionError && <Alert tone="danger">{actionError}</Alert>}
      </div>
    </Panel>
  );
}

export function ThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  const { user } = useAuth();
  const signedIn = !!user;
  const { toast } = useToast();
  const t = useT();
  const navigate = useNavigate();
  const [thread, setThread] = useState<ForumThreadDetail | null>(null);
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const [quoting, setQuoting] = useState<ForumPost | null>(null);
  const [link, setLink] = useState<LinkRef>({ link_type: "", link_id: null });
  const [posting, setPosting] = useState(false);
  const [gateError, setGateError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  // HARD thread deletion is the admin tier's alone (operators +
  // community admins) — the server enforces the same line; plain
  // moderators never see the control.
  const canDeleteThread =
    !!user && (user.is_operator || user.role === "community_admin");

  const removeThread = async () => {
    if (!threadId || !thread) return;
    if (
      !window.confirm(
        t("forum.deleteThread.confirm").replace("{title}", thread.title),
      )
    )
      return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteForumThread(threadId);
      toast(t("forum.deleteThread.done"));
      navigate(`/forum/category/${thread.category_id}`);
    } catch (err) {
      setDeleteError(
        err instanceof ApiError ? err.message : t("forum.deleteThread.error"),
      );
    } finally {
      setDeleting(false);
    }
  };

  const load = useCallback(async () => {
    if (!threadId) return;
    try {
      setThread(await getThread(threadId, signedIn));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This thread couldn't be loaded.");
    }
  }, [threadId, signedIn]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!threadId) return;
    setPosting(true);
    setGateError(null);
    setFormError("");
    try {
      const post = await createReply(threadId, {
        body: reply.trim(),
        quote_post_id: quoting?.id ?? null,
        link_type: link.link_type,
        link_id: link.link_id,
      });
      setReply("");
      setQuoting(null);
      setLink({ link_type: "", link_id: null });
      if (post.status === "held") {
        toast("Your reply is waiting for moderation — it'll appear once it's released.");
      }
      await load();
    } catch (err) {
      if (isGateError(err)) setGateError(err);
      else setFormError(err instanceof ApiError ? err.message : "The reply couldn't be posted.");
    } finally {
      setPosting(false);
    }
  };

  if (error) {
    return (
      <div style={{ display: "grid", gap: "1rem" }}>
        <Breadcrumbs
          items={[
            { label: "Home", to: "/" },
            { label: "Community Forum", to: "/forum" },
            { label: "Thread" },
          ]}
        />
        <Alert tone="danger">{error}</Alert>
      </div>
    );
  }
  if (thread === null) return <Spinner />;

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <Breadcrumbs
        items={[
          { label: "Home", to: "/" },
          { label: "Community Forum", to: "/forum" },
          { label: "Category", to: `/forum/category/${thread.category_id}` },
          { label: thread.title },
        ]}
      />
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "baseline", flexWrap: "wrap" }}>
        {thread.pinned && <Badge tone="accent">Pinned</Badge>}
        {thread.locked && <Badge tone="neutral">Locked</Badge>}
        {thread.held && <Badge tone="warning">Waiting for moderation</Badge>}
        <h1 style={{ margin: 0 }}>{thread.title}</h1>
        <FavoriteStar kind="thread" targetId={thread.id} signedIn={signedIn} />
      </div>
      {canDeleteThread && (
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <div>
            <Button variant="danger" size="sm" onClick={removeThread} disabled={deleting}>
              {t("forum.deleteThread.button")}
            </Button>
          </div>
          {deleteError && <Alert tone="danger">{deleteError}</Alert>}
        </div>
      )}
      <div style={{ display: "grid", gap: "0.75rem" }}>
        {thread.posts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            signedIn={signedIn}
            onChanged={load}
            onQuote={(p) => {
              setQuoting(p);
              document.getElementById("forum-reply-box")?.focus();
            }}
          />
        ))}
      </div>
      {thread.locked ? (
        <Alert tone="info">
          This thread is locked — it can be read, but no new replies can be posted.
        </Alert>
      ) : signedIn ? (
        <Panel>
          <form onSubmit={submit} style={{ display: "grid", gap: "0.75rem" }}>
            <h2 style={{ margin: 0 }}>Reply</h2>
            {gateError && <GateNote error={gateError} />}
            {formError && <Alert tone="danger">{formError}</Alert>}
            {quoting && (
              <blockquote
                style={{
                  margin: 0,
                  padding: "0.5rem 0.75rem",
                  borderLeft: "3px solid var(--edge)",
                  color: "var(--text-muted)",
                }}
              >
                Quoting <strong>{quoting.author.display_name}</strong>: {quoting.body.slice(0, 200)}
                {"  "}
                <Button variant="ghost" size="sm" type="button" onClick={() => setQuoting(null)}>
                  Drop quote
                </Button>
              </blockquote>
            )}
            <TextArea
              id="forum-reply-box"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={5}
              placeholder="Share what you know…"
            />
            <LinkPicker value={link} onChange={setLink} signedIn={signedIn} />
            <div>
              <Button type="submit" disabled={posting}>
                {posting ? "Posting…" : "Post reply"}
              </Button>
            </div>
          </form>
        </Panel>
      ) : (
        <Alert tone="info">
          <Link to="/login">Log in</Link> to reply — reading is open to everyone.
        </Alert>
      )}
    </div>
  );
}
