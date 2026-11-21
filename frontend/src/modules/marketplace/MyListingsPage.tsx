/** Tools For Sale — My listings & deals (owner surface).
 *
 *  My listings with their lifecycle actions (edit, mark sold with
 *  the buyer identified — from the listing's conversation
 *  participants or by exact account number — remove, relist,
 *  delete), and My deals: every completed interaction with its
 *  double-blind rating state. Ratings stay hidden BOTH ways
 *  until both sides submit (or 14 days pass) — the API enforces
 *  it; this page just renders what it may show. */

import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  FormField,
  Modal,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  LinkButton,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import {
  deleteListing,
  getBuyerCandidates,
  listMine,
  listMyInteractions,
  markSold,
  reactivateListing,
  removeListing,
  reportRating,
  submitRating,
} from "./api";
import { priceLabel } from "./pages";
import type { BuyerCandidate, Interaction, OwnerListing } from "./types";
import { SoldSection } from "../inventory/components/SoldSection";

/** Report a published review as abusive (gap wave 1) — the
 *  report lands in the moderation queue's Ratings section. */
function ReportRatingButton({ ratingId }: { ratingId: string }) {
  const { toast } = useToast();
  async function onReport() {
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
  return (
    <Button type="button" variant="secondary" onClick={() => void onReport()}>
      Report review
    </Button>
  );
}

function Stars({ value }: { value: number }) {
  return (
    <span aria-label={`${value} out of 5 stars`} style={{ letterSpacing: "0.1em" }}>
      {"★".repeat(value)}
      {"☆".repeat(5 - value)}
    </span>
  );
}

function StarPicker({
  value,
  onChange,
}: {
  value: number;
  onChange: (stars: number) => void;
}) {
  return (
    <div style={{ display: "flex", gap: "0.25rem" }} role="radiogroup" aria-label="Your rating">
      {[1, 2, 3, 4, 5].map((stars) => (
        <button
          key={stars}
          type="button"
          role="radio"
          aria-checked={value === stars}
          onClick={() => onChange(stars)}
          style={{
            fontSize: "1.5rem",
            lineHeight: 1,
            background: "none",
            border: "none",
            cursor: "pointer",
            color: stars <= value ? "var(--accent)" : "var(--text-muted)",
            padding: "0.1rem",
          }}
        >
          {stars <= value ? "★" : "☆"}
        </button>
      ))}
    </div>
  );
}

function RatingForm({
  interaction,
  onDone,
}: {
  interaction: Interaction;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [stars, setStars] = useState(5);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await submitRating(interaction.id, stars, text.trim());
      toast(
        "Rating saved. It stays private until both sides have rated — or 14 days pass.",
        { title: "Thanks", tone: "success" },
      );
      onDone();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save that rating.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "0.6rem" }}>
      <StarPicker value={stars} onChange={setStars} />
      <FormField label="Say a line about the deal (optional)" htmlFor={`mk-rate-${interaction.id}`}>
        <TextArea
          id={`mk-rate-${interaction.id}`}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={500}
        />
      </FormField>
      <div>
        <Button type="submit" loading={saving}>
          Submit rating
        </Button>
      </div>
    </form>
  );
}

function DealRow({ interaction, onChanged }: { interaction: Interaction; onChanged: () => void }) {
  const mine = interaction.my_rating;
  const theirs = interaction.their_rating;
  return (
    <Panel>
      <div style={{ display: "grid", gap: "0.6rem" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "0.5rem",
            alignItems: "baseline",
          }}
        >
          <strong>{interaction.context_title || "Completed deal"}</strong>
          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
            with{" "}
            <Link to={`/users/${interaction.other_user_id}`}>
              {interaction.other_name}
            </Link>{" "}
            · {new Date(interaction.completed_at).toLocaleDateString()}
          </span>
        </div>
        {mine ? (
          mine.removed ? (
            <span style={{ color: "var(--text-muted)" }}>
              Your rating was removed by a moderator.
            </span>
          ) : (
            <span>
              Your rating: <Stars value={mine.stars ?? 0} />
              {mine.text ? ` — “${mine.text}”` : ""}
              {!mine.published && (
                <span style={{ color: "var(--text-muted)" }}>
                  {" "}
                  (private until both sides rate, or 14 days pass)
                </span>
              )}
            </span>
          )
        ) : (
          <RatingForm interaction={interaction} onDone={onChanged} />
        )}
        {theirs ? (
          theirs.removed ? (
            <span style={{ color: "var(--text-muted)" }}>
              Their rating of you was removed by a moderator.
            </span>
          ) : (
            <span>
              Their rating of you: <Stars value={theirs.stars ?? 0} />
              {theirs.text ? ` — “${theirs.text}”` : ""}{" "}
              {theirs.id && (
                <ReportRatingButton ratingId={theirs.id} />
              )}
            </span>
          )
        ) : (
          <span style={{ color: "var(--text-muted)" }}>
            {interaction.their_rating_submitted
              ? "They've rated you — it publishes when you've rated too, or after 14 days."
              : "They haven't rated you yet."}
          </span>
        )}
      </div>
    </Panel>
  );
}

function SoldModal({
  listing,
  onClose,
  onDone,
}: {
  listing: OwnerListing;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [candidates, setCandidates] = useState<BuyerCandidate[] | null>(null);
  const [picked, setPicked] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getBuyerCandidates(listing.id)
      .then((rows) => {
        if (!cancelled) setCandidates(rows);
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [listing.id]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const body: { buyer_user_id?: string; buyer_account_number?: string } = {};
      if (picked) body.buyer_user_id = picked;
      else if (accountNumber.trim()) body.buyer_account_number = accountNumber.trim();
      await markSold(listing.id, body);
      toast(
        body.buyer_user_id || body.buyer_account_number
          ? t("marketplace.sold.markedRated")
          : t("marketplace.sold.marked"),
        { title: t("marketplace.sold.soldTitle"), tone: "success" },
      );
      onDone();
      onClose();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("marketplace.sold.failed"), {
        title: t("marketplace.row.errorTitle"),
        tone: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={t("marketplace.sold.title").replace("{title}", listing.title)} onClose={onClose}>
      <form
        onSubmit={onSubmit}
        style={{ display: "grid", gap: "0.9rem", minWidth: "min(420px, 80vw)" }}
      >
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          {t("marketplace.sold.body")}
        </p>
        {candidates === null ? (
          <Spinner />
        ) : candidates.length > 0 ? (
          <FormField label={t("marketplace.sold.buyer")} htmlFor="mk-sold-buyer">
            <Select
              id="mk-sold-buyer"
              value={picked}
              onChange={(event) => setPicked(event.target.value)}
            >
              <option value="">{t("marketplace.sold.pickPlaceholder")}</option>
              {candidates.map((candidate) => (
                <option key={candidate.user_id} value={candidate.user_id}>
                  {candidate.name}
                </option>
              ))}
            </Select>
          </FormField>
        ) : null}
        <FormField label={t("marketplace.sold.accountNumber")} htmlFor="mk-sold-account">
          <TextInput
            id="mk-sold-account"
            value={accountNumber}
            onChange={(event) => setAccountNumber(event.target.value)}
            placeholder="TV-MS-000159"
            disabled={!!picked}
          />
        </FormField>
        <div style={{ display: "flex", gap: "0.6rem", justifyContent: "flex-end" }}>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={saving}>
            {t("marketplace.row.markSold")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ListingRow({
  listing,
  onChanged,
}: {
  listing: OwnerListing;
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [soldOpen, setSoldOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function act(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      toast(message, { title: t("marketplace.row.doneTitle"), tone: "success" });
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("marketplace.row.errorBody"), {
        title: t("marketplace.row.errorTitle"),
        tone: "danger",
      });
    }
  }

  return (
    <Panel>
      <div style={{ display: "grid", gap: "0.55rem" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "0.6rem",
            alignItems: "baseline",
            flexWrap: "wrap",
          }}
        >
          <strong>{listing.title}</strong>
          <span>{priceLabel(listing)}</span>
        </div>
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          <Badge tone={listing.listing_type === "wanted" ? "accent" : "neutral"}>
            {listing.listing_type === "wanted" ? t("marketplace.row.wanted") : t("marketplace.row.forSale")}
          </Badge>
          <Badge
            tone={
              listing.status === "active"
                ? "success"
                : listing.status === "sold"
                  ? "accent"
                  : "neutral"
            }
          >
            {listing.status === "active"
              ? t("marketplace.row.onBoard")
              : listing.status === "sold"
                ? t("marketplace.row.sold")
                : t("marketplace.row.removed")}
          </Badge>
          {listing.source_kind && (
            <Badge tone="neutral">{t("marketplace.row.fromInventory")}</Badge>
          )}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <LinkButton to={`/marketplace/${listing.id}/edit`} variant="secondary">{t("marketplace.row.edit")}</LinkButton>
          {listing.status === "active" && (
            <>
              <Button type="button" onClick={() => setSoldOpen(true)}>
                {t("marketplace.row.markSold")}
              </Button>
              <button
                type="button"
                className="tv-list-remove-btn"
                aria-label={`${t("marketplace.row.remove")}: ${listing.title}`}
                title={t("marketplace.row.remove")}
                onClick={() =>
                  void act(() => removeListing(listing.id), t("marketplace.row.removedToast"))
                }
              >
                {"−"}
              </button>
            </>
          )}
          {listing.status === "removed" && (
            <Button
              type="button"
              onClick={() =>
                void act(() => reactivateListing(listing.id), t("marketplace.row.backToast"))
              }
            >
              {t("marketplace.row.putBack")}
            </Button>
          )}
          <Button
            type="button"
            variant="danger"
            onClick={() => setConfirmDelete(true)}
          >
            {t("marketplace.row.delete")}
          </Button>
        </div>
      </div>
      {soldOpen && (
        <SoldModal
          listing={listing}
          onClose={() => setSoldOpen(false)}
          onDone={onChanged}
        />
      )}
      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("marketplace.row.deleteTitle")}
        size="sm"
        footer={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirmDelete(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => {
                setConfirmDelete(false);
                void act(() => deleteListing(listing.id), t("marketplace.row.deletedToast"));
              }}
            >
              {t("marketplace.row.delete")}
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>{t("marketplace.row.deleteBody")}</p>
      </Modal>
    </Panel>
  );
}

function MyContent() {
  const t = useT();
  const [listings, setListings] = useState<OwnerListing[] | null>(null);
  const [deals, setDeals] = useState<Interaction[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [mine, interactions] = await Promise.all([
        listMine(),
        listMyInteractions(),
      ]);
      setListings(mine);
      setDeals(interactions);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("marketplace.mine.loadFailed"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
      <Breadcrumbs
        items={[
          { label: t("nav.marketplace"), to: "/marketplace" },
          { label: t("marketplace.mine.title") },
        ]}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          flexWrap: "wrap",
          gap: "0.6rem",
        }}
      >
        <h1 style={{ margin: 0 }}>{t("marketplace.mine.title")}</h1>
        <LinkButton to="/marketplace/new">{t("marketplace.mine.listAnItem")}</LinkButton>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {listings === null && !error && <Spinner />}

      {listings !== null && (
        <>
          <h2 style={{ margin: "0.4rem 0 0" }}>{t("marketplace.mine.myListings")}</h2>
          {listings.length === 0 && (
            <Panel>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("marketplace.mine.emptyBefore")}{" "}
                <Link to="/marketplace/new">{t("marketplace.mine.emptyLink")}</Link>
                {t("marketplace.mine.emptyAfter")}
              </p>
            </Panel>
          )}
          {listings.map((listing) => (
            <ListingRow key={listing.id} listing={listing} onChanged={() => void load()} />
          ))}
        </>
      )}

      {/* Sold items (owner spec 2026-10-25): the sale ledger
          moved here from the Inventory page — every recorded
          sale (listed or not) with its totals and Undo. The
          section carries its own heading, fetches the ledger
          itself, and hides itself for accounts whose groups
          don't include the inventory module. */}
      <SoldSection />

      {deals !== null && (
        <>
          <h2 style={{ margin: "0.4rem 0 0" }}>{t("marketplace.mine.myDeals")}</h2>
          {deals.length === 0 && (
            <Panel>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("marketplace.mine.dealsEmpty")}
              </p>
            </Panel>
          )}
          {deals.map((deal) => (
            <DealRow key={deal.id} interaction={deal} onChanged={() => void load()} />
          ))}
        </>
      )}
    </div>
  );
}

export default function MyListingsPage() {
  return (
    <RequireAuth>
      <MyContent />
    </RequireAuth>
  );
}
