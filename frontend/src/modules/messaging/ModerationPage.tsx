import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Panel,
  Select,
  Spinner,
  TextInput,
  useToast,
  HrefButton,
} from "../../components";
import "./moderation.css";
import { ApiError } from "../../lib/api";
import { RequireAuth, useAuth } from "../core";
import {
  discardFeedbackTarget,
  dismissFeedbackReport,
  getFeedbackHeld,
  getFeedbackReports,
  releaseFeedbackTarget,
  removeFeedbackTarget,
} from "../feedback/api";
import type { FeedbackHeld, FeedbackReport } from "../feedback/types";
import {
  createBlock,
  discardForumPost,
  dismissForumReport,
  getForumHeld,
  getForumReports,
  liftBlock,
  listBlocks,
  releaseForumPost,
  removeForumPost,
  setForumThreadLock,
  setForumThreadPin,
  wipeForumPosts,
} from "../forum/api";
import type { CommunityBlock, ForumHeld, ForumReport } from "../forum/types";
import {
  dismissRatingReport,
  listRatingReports,
  removeRatingReport,
} from "../marketplace/api";
import type { RatingReport } from "../marketplace/types";
import {
  dismissPrintReport,
  getPrintReports,
  modRemovePrintComment,
  modRemovePrintFile,
} from "../prints/api";
import type { PrintReport } from "../prints/types";
import {
  banUser,
  discardMessage,
  dismissReport,
  getModThread,
  listHeld,
  listReports,
  releaseMessage,
  wipeAllFromUser,
  wipeMessage,
} from "./api";
import type { HeldItem, ModThread, ReportItem } from "./types";

/**
 * The moderation queue (role ladder: moderator / community_admin /
 * operator). Reports and firewall holds land here; every action
 * is audit-logged server-side. Not part of the Admin panel — the
 * queue is community work, and moderators are not operators.
 */
function ModerationContent() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [reports, setReports] = useState<ReportItem[] | null>(null);
  const [held, setHeld] = useState<HeldItem[] | null>(null);
  const [forumReports, setForumReports] = useState<ForumReport[] | null>(null);
  const [forumHeld, setForumHeld] = useState<ForumHeld[] | null>(null);
  const [feedbackReports, setFeedbackReports] = useState<FeedbackReport[] | null>(null);
  const [feedbackHeld, setFeedbackHeld] = useState<FeedbackHeld[] | null>(null);
  const [ratingReports, setRatingReports] = useState<RatingReport[] | null>(null);
  const [printReports, setPrintReports] = useState<PrintReport[] | null>(null);
  const [blocks, setBlocks] = useState<CommunityBlock[] | null>(null);
  const [blockAccount, setBlockAccount] = useState("");
  const [blockFeature, setBlockFeature] = useState("forums");
  const [blockReason, setBlockReason] = useState("");
  const [viewing, setViewing] = useState<ModThread | null>(null);
  const [error, setError] = useState("");

  const allowed =
    user?.is_operator || user?.role === "moderator" || user?.role === "community_admin";

  // Community blocks (admin lane, owner ruling 2026-11-06):
  // imposing and lifting take a god or moderator_admin seat —
  // the server enforces the same gate; moderators see the
  // list but get no block/lift controls.
  const canBlock = Boolean(
    user?.is_operator || user?.tier === "god" || user?.tier === "moderator_admin",
  );

  const load = useCallback(async () => {
    try {
      const [r, h, fr, fh, rr, fbr, fbh, bl, pr] = await Promise.all([
        listReports("open"),
        listHeld(),
        getForumReports("open"),
        getForumHeld(),
        listRatingReports("open"),
        getFeedbackReports("open"),
        getFeedbackHeld(),
        listBlocks(),
        getPrintReports(),
      ]);
      setReports(r);
      setHeld(h);
      setForumReports(fr);
      setForumHeld(fh);
      setRatingReports(rr);
      setFeedbackReports(fbr);
      setFeedbackHeld(fbh);
      setBlocks(bl);
      setPrintReports(pr.reports);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the queue.");
    }
  }, []);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  function act(fn: () => Promise<unknown>, ok: string) {
    return async () => {
      try {
        await fn();
        toast(ok, { title: "Done", tone: "success" });
        setViewing(null);
        await load();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "That action failed.", {
          title: "Something went wrong",
          tone: "danger",
        });
      }
    };
  }

  if (!allowed) {
    return (
      <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
        <h1 style={{ margin: 0 }}>Moderation</h1>
        <Panel title="Moderators only">
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            The moderation queue is for community moderators and
            operators. If someone is harassing you, open the
            conversation and use Report — it lands here for review.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "960px" }}>
      <h1 style={{ margin: 0 }}>Moderation queue</h1>
      {error && <Alert tone="danger">{error}</Alert>}

      <Panel title={`Open reports (${reports?.length ?? "…"})`}>
        {reports === null ? (
          <Spinner />
        ) : reports.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No open reports.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {reports.map((report) => (
              <div
                key={report.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{report.participant_names.join(" ↔ ") || "Conversation"}</strong>
                  {report.anchor_title && <> · about “{report.anchor_title}”</>}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  Reported by {report.reporter_name}: {report.reason || "(no reason given)"}
                </span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void getModThread(report.thread_id).then(setViewing).catch(() =>
                        toast("Couldn't open that thread.", { tone: "danger" }),
                      )
                    }
                  >
                    View thread
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(
                        () => dismissReport(report.id, "Reviewed from the queue"),
                        "Report dismissed.",
                      )()
                    }
                  >
                    Dismiss
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Held by the spam firewall (${held?.length ?? "…"})`}>
        {held === null ? (
          <Spinner />
        ) : held.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Nothing is being held. Blocked domains, scam-style lures,
            and copy-paste blasts land here instead of reaching members.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {held.map((item) => (
              <div
                key={item.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{item.sender_name}</strong> → {item.recipient_name}
                  {item.flags.map((flag) => (
                    <Badge key={flag} tone="warning" >
                      {" "}{flag}
                    </Badge>
                  ))}
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.body}</span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void act(() => releaseMessage(item.id), "Message released to the recipient.")()}
                  >
                    Release
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void act(() => discardMessage(item.id), "Message discarded.")()}
                  >
                    Discard
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      void act(() => banUser(item.sender_id), "Account banned and deactivated.")()
                    }
                  >
                    Ban sender
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Forum reports (${forumReports?.length ?? "…"})`}>
        {forumReports === null ? (
          <Spinner />
        ) : forumReports.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No open forum reports.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {forumReports.map((report) => (
              <div
                key={report.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{report.post_author_name}</strong> in “{report.thread_title}”
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {report.post_excerpt || <em>(no visible text)</em>}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  Reported by {report.reporter_name}: {report.reason || "(no reason given)"}
                </span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      void act(() => removeForumPost(report.post_id, "Removed after a member report."), "Post removed.")()
                    }
                  >
                    Remove post
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(() => dismissForumReport(report.id, ""), "Report dismissed.")()
                    }
                  >
                    Dismiss
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(() => setForumThreadPin(report.thread_id, true), "Thread pinned.")()
                    }
                  >
                    Pin thread
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(() => setForumThreadLock(report.thread_id, true), "Thread locked.")()
                    }
                  >
                    Lock thread
                  </Button>
                  {report.post_author_id && (
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() =>
                        void act(
                          () => wipeForumPosts(report.post_author_id as string),
                          "All their forum posts removed.",
                        )()
                      }
                    >
                      Remove all posts by {report.post_author_name}
                    </Button>
                  )}
                  {canBlock && report.post_author_id && (
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() =>
                        void act(
                          () =>
                            createBlock({
                              user_id: report.post_author_id as string,
                              feature: "forums",
                              reason: report.reason || "Blocked from a forum report.",
                            }),
                          `${report.post_author_name} is blocked from the forums.`,
                        )()
                      }
                    >
                      Block author from the forums
                    </Button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Rating reports (${ratingReports?.length ?? "…"})`}>
        {ratingReports === null ? (
          <Spinner />
        ) : ratingReports.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No open rating reports.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {ratingReports.map((report) => (
              <div
                key={report.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{report.rater_name}</strong>
                  {report.rating_stars !== null && <> · {"★".repeat(report.rating_stars)}</>}{" "}
                  on <strong>{report.ratee_name}</strong>
                  {report.context_title && <> · “{report.context_title}”</>}
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {report.rating_text || <em>(no review text)</em>}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  Reported by {report.reporter_name}: {report.reason || "(no reason given)"}
                </span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      void act(
                        () => removeRatingReport(report.id, "Removed from the moderation queue"),
                        "Review removed — it no longer counts toward their rating.",
                      )()
                    }
                  >
                    Remove review
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(
                        () => dismissRatingReport(report.id, "Reviewed from the queue"),
                        "Report dismissed — the review stands.",
                      )()
                    }
                  >
                    Dismiss
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Held forum posts (${forumHeld?.length ?? "…"})`}>
        {forumHeld === null ? (
          <Spinner />
        ) : forumHeld.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            No forum posts are being held. The spam firewall holds
            blocklisted links and scam-style lures here instead of
            publishing them.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {forumHeld.map((item) => (
              <div
                key={item.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{item.author_name}</strong> in “{item.thread_title}”
                  {item.is_opener && <Badge tone="neutral"> thread opener</Badge>}
                  {item.flags.map((flag) => (
                    <Badge key={flag} tone="warning">
                      {" "}{flag}
                    </Badge>
                  ))}
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.body}</span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void act(() => releaseForumPost(item.id), "Post released to the forum.")()}
                  >
                    Release
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void act(() => discardForumPost(item.id), "Post discarded.")()}
                  >
                    Discard
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      void act(() => wipeForumPosts(item.author_id), "All their forum posts removed.")()
                    }
                  >
                    Remove all posts by this member
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Feedback reports (${feedbackReports?.length ?? "…"})`}>
        {feedbackReports === null ? (
          <Spinner />
        ) : feedbackReports.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No open feedback reports.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {feedbackReports.map((report) => (
              <div
                key={report.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{report.target_author_name}</strong> — {report.target_kind} in “
                  {report.post_title}”
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {report.target_excerpt || <em>(no visible text)</em>}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  Reported by {report.reporter_name}: {report.reason || "(no reason given)"}
                </span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() =>
                      void act(
                        () =>
                          removeFeedbackTarget(
                            report.target_kind,
                            report.target_id,
                            "Removed after a member report.",
                          ),
                        "Removed.",
                      )()
                    }
                  >
                    Remove {report.target_kind}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(() => dismissFeedbackReport(report.id), "Report dismissed.")()
                    }
                  >
                    Dismiss
                  </Button>
                  {report.post_id && (
                    <HrefButton href={`/feedback/post/${report.post_id}`} target="_blank" rel="noreferrer" variant="secondary">View post</HrefButton>
                  )}
                  {canBlock && report.target_author_id && (
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() =>
                        void act(
                          () =>
                            createBlock({
                              user_id: report.target_author_id as string,
                              feature: "feedback_boards",
                              reason: report.reason || "Blocked from a board report.",
                            }),
                          `${report.target_author_name} is blocked from the boards.`,
                        )()
                      }
                    >
                      Block author from the boards
                    </Button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`3D print file reports (${printReports?.length ?? "…"})`}>
        {printReports === null ? (
          <Spinner />
        ) : printReports.length === 0 ? (
          <p className="tv-blocks-empty">
            No open print reports. Flags on print files and their
            comments land here — the shelf is shop prints only, so
            off-topic files are the usual case.
          </p>
        ) : (
          <div className="tv-blocks-list">
            {printReports.map((report) => (
              <div key={report.id} className="tv-blocks-row">
                <span>
                  {report.target_kind === "comment" ? (
                    <>
                      Comment on <strong>{report.file_title}</strong>
                      {report.comment_excerpt && <> · “{report.comment_excerpt}”</>}
                    </>
                  ) : (
                    <>
                      Print file <strong>{report.file_title}</strong>
                    </>
                  )}
                </span>
                <span className="tv-blocks-meta">
                  Reported by {report.reporter_name}: {report.reason || "(no reason given)"}
                </span>
                <span className="tv-blocks-actions">
                  <HrefButton
                    href={`/3dprints/${report.file_id}`}
                    target="_blank"
                    rel="noreferrer"
                    variant="secondary"
                  >
                    View file
                  </HrefButton>
                  {canBlock && report.target_kind === "file" && report.file_status === "live" && (
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() =>
                        void act(
                          () => modRemovePrintFile(report.file_id, report.reason || "Removed from the moderation queue."),
                          "Print file removed — it is off the shelf.",
                        )()
                      }
                    >
                      Remove file
                    </Button>
                  )}
                  {canBlock && report.target_kind === "comment" && report.comment_id && report.comment_status === "live" && (
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() =>
                        void act(
                          () => modRemovePrintComment(report.comment_id as string, report.reason || "Removed from the moderation queue."),
                          "Comment removed.",
                        )()
                      }
                    >
                      Remove comment
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(() => dismissPrintReport(report.id, ""), "Report dismissed.")()
                    }
                  >
                    Dismiss
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Held feedback (${feedbackHeld?.length ?? "…"})`}>
        {feedbackHeld === null ? (
          <Spinner />
        ) : feedbackHeld.length === 0 ? (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            No feedback is being held. The spam firewall holds
            blocklisted links and scam-style lures here instead of
            publishing them.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {feedbackHeld.map((item) => (
              <div
                key={`${item.target_kind}-${item.id}`}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.7rem 0.9rem",
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                <span>
                  <strong>{item.author_name}</strong> — {item.target_kind} in “
                  {item.post_title}”
                  {item.flags.map((flag) => (
                    <Badge key={flag} tone="warning">
                      {" "}{flag}
                    </Badge>
                  ))}
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.body}</span>
                <span style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(
                        () => releaseFeedbackTarget(item.target_kind, item.id),
                        "Released to the board.",
                      )()
                    }
                  >
                    Release
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      void act(
                        () => discardFeedbackTarget(item.target_kind, item.id),
                        "Discarded.",
                      )()
                    }
                  >
                    Discard
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Community blocks (${blocks?.length ?? "…"})`}>
        {blocks === null ? (
          <Spinner />
        ) : blocks.length === 0 ? (
          <p className="tv-blocks-empty">
            Nobody is blocked from a community feature right now.
            A block is per-feature and surgical — the member keeps
            their account and everything else; they just can't
            post in the blocked feature, and they're told they
            can open a support ticket to ask for it back.
          </p>
        ) : (
          <div className="tv-blocks-list">
            {blocks.map((block) => (
              <div key={block.id} className="tv-blocks-row">
                <span>
                  <strong>{block.user_name}</strong> ({block.account_number}) — blocked
                  from {block.feature_label}
                </span>
                {block.reason && <span>{block.reason}</span>}
                <span className="tv-blocks-meta">
                  Blocked by {block.blocked_by_name} ·{" "}
                  {new Date(block.created_at).toLocaleDateString()}
                </span>
                {canBlock && (
                  <span className="tv-blocks-actions">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() =>
                        void act(() => liftBlock(block.id), `${block.user_name} can post in ${block.feature_label} again.`)()
                      }
                    >
                      Lift block
                    </Button>
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
        {canBlock && (
          <form
            className="tv-blocks-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(
                () =>
                  createBlock({
                    account_number: blockAccount.trim(),
                    feature: blockFeature,
                    reason: blockReason.trim(),
                  }),
                "Block imposed — the member has been notified.",
              )().then(() => {
                setBlockAccount("");
                setBlockReason("");
              });
            }}
          >
            <FormField label="Block a member by account number" htmlFor="block-account">
              <TextInput
                id="block-account"
                value={blockAccount}
                onChange={(e) => setBlockAccount(e.target.value)}
                placeholder="TV-M-000000"
                required
              />
            </FormField>
            <FormField label="Feature" htmlFor="block-feature">
              <Select
                id="block-feature"
                value={blockFeature}
                onChange={(e) => setBlockFeature(e.target.value)}
              >
                <option value="forums">The community forums</option>
                <option value="feedback_boards">The Bug Reports and Feature Requests boards</option>
                <option value="community_parts">Community Parts</option>
                <option value="print_files">The 3D print files</option>
              </Select>
            </FormField>
            <FormField label="Reason (the member sees this)" htmlFor="block-reason">
              <TextInput
                id="block-reason"
                value={blockReason}
                onChange={(e) => setBlockReason(e.target.value)}
                maxLength={500}
              />
            </FormField>
            <span className="tv-blocks-actions">
              <Button type="submit" variant="danger">
                Block member
              </Button>
            </span>
          </form>
        )}
      </Panel>

      {viewing && (
        <Panel title={`Thread — ${viewing.participant_names.join(" ↔ ")}`}>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {viewing.messages.map((message) => (
              <div
                key={message.id}
                style={{
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.5rem 0.8rem",
                  display: "grid",
                  gap: "0.2rem",
                }}
              >
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {message.sender_name} · {message.status}
                  {message.flags.length > 0 && ` · ${message.flags.join(", ")}`}
                </span>
                <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {message.body || <em>(removed)</em>}
                </span>
                {message.status === "held" && (
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    <Button type="button" variant="secondary" onClick={() => void act(() => releaseMessage(message.id), "Released.")()}>
                      Release
                    </Button>
                    <Button type="button" variant="secondary" onClick={() => void act(() => discardMessage(message.id), "Discarded.")()}>
                      Discard
                    </Button>
                  </span>
                )}
                {message.status === "sent" && (
                  <span>
                    <Button type="button" variant="secondary" onClick={() => void act(() => wipeMessage(message.id), "Message wiped.")()}>
                      Wipe message
                    </Button>
                  </span>
                )}
              </div>
            ))}
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.4rem" }}>
              <Button
                type="button"
                variant="danger"
                onClick={() =>
                  void act(
                    () => wipeAllFromUser(viewing.participant_low_id),
                    "All their messages wiped.",
                  )()
                }
              >
                Wipe all from {viewing.participant_names[0] || "first member"}
              </Button>
              <Button
                type="button"
                variant="danger"
                onClick={() =>
                  void act(
                    () => wipeAllFromUser(viewing.participant_high_id),
                    "All their messages wiped.",
                  )()
                }
              >
                Wipe all from {viewing.participant_names[1] || "second member"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setViewing(null)}>
                Close thread
              </Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}

export default function ModerationPage() {
  return (
    <RequireAuth>
      <ModerationContent />
    </RequireAuth>
  );
}
