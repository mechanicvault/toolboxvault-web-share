import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Panel,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useAuth } from "../core";
import { getPublicReputation, reportRating } from "../marketplace/api";
import type { PublishedRating } from "../marketplace/types";
import { getPublicProfile, openThread } from "./api";
import type { PublicProfile } from "./types";

/**
 * The public seller profile (community suite): what a listing is
 * allowed to say about its seller — display name, member since,
 * the coarse area they chose to share, a phone number ONLY while
 * they opted in, and the reputation summary + published reviews
 * (REAL since the Tools For Sale build: the marketplace engine's
 * one aggregate; reviews appear only once published under the
 * double-blind rule). Reachable signed out; messaging requires
 * an account.
 */
export default function PublicProfilePage() {
  const { userId } = useParams<{ userId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [reviews, setReviews] = useState<PublishedRating[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!userId) return;
    let live = true;
    getPublicProfile(userId)
      .then((p) => {
        if (live) setProfile(p);
      })
      .catch((err) => {
        if (live) {
          setError(
            err instanceof ApiError ? err.message : "That profile isn't available.",
          );
        }
      });
    // The published reviews ride the marketplace's public
    // reputation endpoint; best-effort (the aggregate above is
    // the summary of record).
    getPublicReputation(userId)
      .then((rep) => {
        if (live) setReviews(rep.ratings);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [userId]);

  async function onReportReview(ratingId: string) {
    const reason = window.prompt(
      "Why are you reporting this review? (Spam, abuse, threats, not about a real deal…)",
      "",
    );
    if (reason === null) return;
    try {
      await reportRating(ratingId, reason.trim());
      toast("Thanks — a moderator will take a look.", {
        title: "Review reported",
        tone: "success",
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't report that review.", {
        title: "Report failed",
        tone: "danger",
      });
    }
  }

  async function onMessage(event: FormEvent) {
    event.preventDefault();
    if (!profile || !draft.trim()) return;
    setSending(true);
    try {
      const thread = await openThread({
        recipient_id: profile.user_id,
        body: draft.trim(),
      });
      toast("Message sent.", { title: "Sent", tone: "success" });
      navigate(`/messages/${thread.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't send that message.", {
        title: "Message not sent",
        tone: "danger",
      });
      setSending(false);
    }
  }

  if (error) {
    return (
      <div style={{ display: "grid", gap: "1rem", maxWidth: "720px" }}>
        <h1 style={{ margin: 0 }}>Member profile</h1>
        <Alert tone="danger">{error}</Alert>
      </div>
    );
  }
  if (!profile) return <Spinner />;

  const rep = profile.reputation;
  const isSelf = user?.id === profile.user_id;

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "720px" }}>
      <h1 style={{ margin: 0 }}>{profile.display_name}</h1>
      <Panel title="Member">
        <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
          <div>
            <dt style={{ color: "var(--text-muted)" }}>Member since</dt>
            <dd style={{ margin: 0 }}>
              {new Date(profile.member_since).toLocaleDateString([], {
                month: "long",
                year: "numeric",
              })}
            </dd>
          </div>
          {profile.area_label && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Area</dt>
              <dd style={{ margin: 0 }}>{profile.area_label}</dd>
            </div>
          )}
          {profile.phone && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Phone</dt>
              <dd style={{ margin: 0 }}>
                <a href={`tel:${profile.phone}`}>{profile.phone}</a>{" "}
                <span style={{ color: "var(--text-muted)" }}>
                  (this member chose to share their number)
                </span>
              </dd>
            </div>
          )}
        </dl>
      </Panel>

      <Panel title="Reputation">
        <div style={{ display: "grid", gap: "0.8rem" }}>
          {rep.count === 0 ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No ratings yet
              {rep.completed_deals > 0
                ? ` — ${rep.completed_deals} completed deal${rep.completed_deals === 1 ? "" : "s"} so far, reviews publish once both sides rate (or after 14 days).`
                : ". Ratings arrive with completed community deals — both sides rate, then both reviews appear together."}
            </p>
          ) : (
            <p style={{ margin: 0 }}>
              ★ {rep.average?.toFixed(1)} from {rep.count} rating
              {rep.count === 1 ? "" : "s"} · {rep.completed_deals} completed deal
              {rep.completed_deals === 1 ? "" : "s"}
            </p>
          )}
          {reviews.map((review) => (
            <div
              key={review.id}
              style={{ borderTop: "1px solid var(--edge)", paddingTop: "0.6rem" }}
            >
              {review.removed ? (
                <>
                  <span style={{ color: "var(--text-muted)" }}>
                    Review removed —{" "}
                    <Link to={`/users/${review.rater_id}`}>{review.rater_name}</Link>
                    {review.context_title && <> · {review.context_title}</>}
                  </span>
                  <p style={{ margin: "0.3rem 0 0", color: "var(--text-muted)" }}>
                    <em>{review.text}</em>
                  </p>
                </>
              ) : (
                <>
                  <span>
                    {"★".repeat(review.stars ?? 0)}
                    {"☆".repeat(5 - (review.stars ?? 0))}
                    {" — "}
                    <Link to={`/users/${review.rater_id}`}>{review.rater_name}</Link>
                    {review.context_title && (
                      <span style={{ color: "var(--text-muted)" }}>
                        {" "}
                        · {review.context_title}
                      </span>
                    )}
                  </span>
                  {review.text && <p style={{ margin: "0.3rem 0 0" }}>{review.text}</p>}
                  {user && user.id !== review.rater_id && (
                    <p style={{ margin: "0.3rem 0 0" }}>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => void onReportReview(review.id)}
                      >
                        Report review
                      </Button>
                    </p>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      </Panel>

      {!isSelf &&
        (user ? (
          <Panel title={`Message ${profile.display_name}`}>
            <form onSubmit={(e) => void onMessage(e)} style={{ display: "grid", gap: "0.6rem" }}>
              <TextInput
                aria-label="Your message"
                placeholder="Ask about a part, a deal, anything…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <div>
                <Button type="submit" disabled={sending || !draft.trim()}>
                  {sending ? "Sending…" : "Send message"}
                </Button>
              </div>
              <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "0.9rem" }}>
                First messages land in their requests — you'll get a
                note when they reply.
              </p>
            </form>
          </Panel>
        ) : (
          <Panel title="Contact">
            <p style={{ margin: 0 }}>
              <Link to="/login">Sign in</Link> or{" "}
              <Link to="/signup">create a free account</Link> to message
              this member.
            </p>
          </Panel>
        ))}
    </div>
  );
}
