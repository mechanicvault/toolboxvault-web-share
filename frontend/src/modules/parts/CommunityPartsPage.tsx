import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  FormField,
  ItemThumb,
  Modal,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { SellerPrice } from "../../components/SellerPrice";
import { ApiError } from "../../lib/api";
import { useAuth } from "../core";
import { SellerRatingBadge } from "../marketplace/SellerRating";
import { openThread } from "../messaging/api";
import { listCommunity, listCommunityPublic, type CommunityFilters } from "./api";
import type { CommunityListing } from "./types";

/**
 * Community Parts — the pool (2026-10-19). Every member's
 * publicly listed spare parts, searchable by year / make / model
 * / engine. Readable signed out (the public payload is the same
 * exact-key listing contract); messaging a seller needs an
 * account. What a listing shows is all a seller chose to publish:
 * never their storage location, never their notes, never an
 * email, and a phone number only while they opted in.
 */

function hasPrice(listing: CommunityListing): boolean {
  return listing.asking_price !== null && listing.asking_price !== "";
}

function vehicleLine(listing: CommunityListing): string {
  return [listing.year, listing.make, listing.model, listing.engine]
    .filter((v) => v !== null && v !== "")
    .join(" · ");
}

function ListingCard({
  listing,
  onOpen,
}: {
  listing: CommunityListing;
  onOpen: (listing: CommunityListing) => void;
}) {
  const photo = listing.photos[0];
  const price = hasPrice(listing);
  return (
    <button
      type="button"
      onClick={() => onOpen(listing)}
      style={{
        textAlign: "left",
        background: "none",
        border: "none",
        padding: 0,
        cursor: "pointer",
        color: "inherit",
      }}
    >
      <Panel className="tv-part-row">
        <div style={{ display: "flex", gap: "0.9rem", alignItems: "center" }}>
          <ItemThumb
            fill
            sizeClass="tv-thumb--s64"
            src={photo?.url ?? null}
            name={listing.title}
          />
          <div style={{ display: "grid", gap: "0.25rem", minWidth: 0 }}>
            <span style={{ fontWeight: 600, overflowWrap: "anywhere" }}>
              {listing.title}
              {listing.quantity > 1 && (
                <>
                  {" "}
                  <Badge tone="neutral">×{listing.quantity}</Badge>
                </>
              )}
              {price && (
                <>
                  {" "}
                  <Badge tone="success">
                    <SellerPrice
                      amount={listing.asking_price}
                      currency={listing.seller_currency}
                    />
                  </Badge>
                </>
              )}
            </span>
            {vehicleLine(listing) && (
              <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                {vehicleLine(listing)}
              </span>
            )}
            <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
              {listing.seller_name}
              <SellerRatingBadge sellerId={listing.seller_id} />
              {listing.area_label && ` · ${listing.area_label}`}
              {listing.category && ` · ${listing.category}`}
              {listing.condition && ` · ${listing.condition}`}
            </span>
          </div>
        </div>
      </Panel>
    </button>
  );
}

function ListingModal({
  listing,
  onClose,
}: {
  listing: CommunityListing;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const price = hasPrice(listing);
  const isMine = user?.id === listing.seller_id;

  async function onMessage(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setSending(true);
    try {
      const thread = await openThread({
        recipient_id: listing.seller_id,
        body: draft.trim(),
        anchor_type: "part",
        anchor_id: listing.id,
      });
      toast("Message sent — it lands in the seller's requests.", {
        title: "Sent",
        tone: "success",
      });
      navigate(`/messages/${thread.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't send that message.", {
        title: "Message not sent",
        tone: "danger",
      });
      setSending(false);
    }
  }

  return (
    <Modal open title={listing.title} onClose={onClose}>
      <div style={{ display: "grid", gap: "0.9rem" }}>
        {listing.photos.length > 0 && (
          <div
            style={{
              display: "grid",
              gap: "var(--space-3)",
              gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 140px), 1fr))",
            }}
          >
            {listing.photos.map((photo) => (
              <img
                key={photo.url}
                src={photo.url}
                alt={photo.filename}
                style={{
                  width: "100%",
                  aspectRatio: "1",
                  objectFit: "cover",
                  borderRadius: "var(--radius)",
                  border: "1px solid var(--edge)",
                }}
              />
            ))}
          </div>
        )}
        <dl style={{ display: "grid", gap: "0.45rem", margin: 0 }}>
          {vehicleLine(listing) && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Fits</dt>
              <dd style={{ margin: 0 }}>{vehicleLine(listing)}</dd>
            </div>
          )}
          {listing.condition && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Condition</dt>
              <dd style={{ margin: 0 }}>{listing.condition}</dd>
            </div>
          )}
          {listing.category && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Category</dt>
              <dd style={{ margin: 0 }}>{listing.category}</dd>
            </div>
          )}
          {price && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Asking price</dt>
              <dd style={{ margin: 0 }}>
                <SellerPrice
                  amount={listing.asking_price}
                  currency={listing.seller_currency}
                />
              </dd>
            </div>
          )}
          <div>
            <dt style={{ color: "var(--text-muted)" }}>Seller</dt>
            <dd style={{ margin: 0 }}>
              <Link to={`/users/${listing.seller_id}`}>{listing.seller_name}</Link>
              <SellerRatingBadge sellerId={listing.seller_id} />
              {listing.area_label && ` · ${listing.area_label}`}
              {" · member since "}
              {new Date(listing.seller_member_since).toLocaleDateString([], {
                month: "short",
                year: "numeric",
              })}
            </dd>
          </div>
          {listing.phone && (
            <div>
              <dt style={{ color: "var(--text-muted)" }}>Phone</dt>
              <dd style={{ margin: 0 }}>
                <a href={`tel:${listing.phone}`}>{listing.phone}</a>{" "}
                <span style={{ color: "var(--text-muted)" }}>
                  (the seller chose to share it)
                </span>
              </dd>
            </div>
          )}
        </dl>

        {isMine ? (
          <Alert tone="info">This is your listing — manage it from My Parts.</Alert>
        ) : user ? (
          <form onSubmit={(e) => void onMessage(e)} style={{ display: "grid", gap: "0.6rem" }}>
            <TextArea
              aria-label={`Message ${listing.seller_name} about this part`}
              rows={3}
              placeholder={`Ask ${listing.seller_name} about this part…`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <div>
              <Button type="submit" disabled={sending || !draft.trim()}>
                {sending ? "Sending…" : "Message seller"}
              </Button>
            </div>
          </form>
        ) : (
          <Alert tone="info">
            <Link to="/login">Sign in</Link> or{" "}
            <Link to="/signup">create a free account</Link> to message the
            seller. Browsing is always free.
          </Alert>
        )}
      </div>
    </Modal>
  );
}

export default function CommunityPartsPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<CommunityFilters>({});
  const [listings, setListings] = useState<CommunityListing[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<CommunityListing | null>(null);

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      const fetchPage = user ? listCommunity : listCommunityPublic;
      fetchPage(filters)
        .then((rows) => {
          if (live) {
            setListings(rows);
            setUnavailable(false);
          }
        })
        .catch((err) => {
          if (!live) return;
          if (err instanceof ApiError && err.status === 404) {
            setUnavailable(true);
            setListings([]);
          } else {
            setError(
              err instanceof ApiError ? err.message : "Couldn't load the pool.",
            );
          }
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [filters, user]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const row of listings ?? []) {
      if (row.category) set.add(row.category);
    }
    return [...set].sort();
  }, [listings]);

  function set<K extends keyof CommunityFilters>(key: K, value: string) {
    setFilters((f) => ({ ...f, [key]: value || undefined }));
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <h1 style={{ margin: 0 }}>Community Parts</h1>
      <p style={{ margin: 0, color: "var(--text-muted)", maxWidth: "46rem" }}>
        Spare parts members have chosen to share with the community.
        Search by the vehicle a part fits — sellers settle payment
        and pickup between themselves; Toolbox Vault doesn't handle
        the money.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      {unavailable ? (
        <Panel title="The pool is resting">
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            The Community Parts pool isn't available right now. Your
            own shelf is unaffected — it's in My Parts.
          </p>
        </Panel>
      ) : (
        <>
          <Panel title="Find a part">
            <div
              style={{
                display: "grid",
                gap: "0.8rem",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
              }}
            >
              <FormField label="Search" htmlFor="pool-q">
                <TextInput
                  id="pool-q"
                  placeholder="Part name or keyword"
                  value={filters.q ?? ""}
                  onChange={(e) => set("q", e.target.value)}
                />
              </FormField>
              <FormField label="Year" htmlFor="pool-year">
                <TextInput
                  id="pool-year"
                  type="number"
                  placeholder="2018"
                  value={filters.year ?? ""}
                  onChange={(e) => set("year", e.target.value)}
                />
              </FormField>
              <FormField label="Make" htmlFor="pool-make">
                <TextInput
                  id="pool-make"
                  placeholder="Chevrolet"
                  value={filters.make ?? ""}
                  onChange={(e) => set("make", e.target.value)}
                />
              </FormField>
              <FormField label="Model" htmlFor="pool-model">
                <TextInput
                  id="pool-model"
                  placeholder="Silverado 1500"
                  value={filters.model ?? ""}
                  onChange={(e) => set("model", e.target.value)}
                />
              </FormField>
              <FormField label="Engine" htmlFor="pool-engine">
                <TextInput
                  id="pool-engine"
                  placeholder="5.3L V8"
                  value={filters.engine ?? ""}
                  onChange={(e) => set("engine", e.target.value)}
                />
              </FormField>
              <FormField label="Category" htmlFor="pool-category">
                <Select
                  id="pool-category"
                  value={filters.category ?? ""}
                  onChange={(e) => set("category", e.target.value)}
                >
                  <option value="">Any category</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                  {filters.category && !categories.includes(filters.category) && (
                    <option value={filters.category}>{filters.category}</option>
                  )}
                </Select>
              </FormField>
            </div>
          </Panel>

          {listings === null ? (
            <Spinner />
          ) : listings.length === 0 ? (
            <Panel title="Nothing listed matches">
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No public parts match that search yet. Members list
                parts from their My Parts shelf — check back, or
                widen the search.
              </p>
            </Panel>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {listings.map((listing) => (
                <ListingCard key={listing.id} listing={listing} onOpen={setSelected} />
              ))}
            </div>
          )}
        </>
      )}
      {selected && (
        <ListingModal listing={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
