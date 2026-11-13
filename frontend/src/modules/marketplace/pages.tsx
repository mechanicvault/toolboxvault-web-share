/** Tools For Sale — the public board + listing detail.
 *
 *  Visible to EVERYONE (signed in or not): the community suite's
 *  read side. Contributing is the gated side (owner surfaces in
 *  MyListingsPage / ListingFormPage, behind the module + the
 *  paid-contribution gate the API enforces).
 *
 *  Cards show only what the seller put on the listing — the
 *  pinned payload — with the seller's rating badge and their
 *  coarse area label. Phones appear only when the seller opted
 *  in. Contact starts an anchored message thread (a request,
 *  under the messaging quarantine rules). */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Breadcrumbs,
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
  LinkButton,
} from "../../components";
import { SellerPrice } from "../../components/SellerPrice";
import { ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/money";
import { useAuth } from "../core";
import { openThread } from "../messaging/api";
import { getBoard, getPublicBoard, getPublicListing, type BoardQuery } from "./api";
import { reputationBadge, type PublicListing } from "./types";

export function priceLabel(listing: PublicListing): string {
  if (listing.price === null) return "Make offer";
  // Wave 3: a listing's price is in the SELLER's currency.
  return formatMoney(listing.price, listing.seller_currency);
}

/** The board price: the seller-currency label + the viewer's
 * approximate hint when the currencies differ. */
export function ListingPrice({ listing }: { listing: PublicListing }) {
  if (listing.price === null) return <>Make offer</>;
  return (
    <SellerPrice amount={listing.price} currency={listing.seller_currency} />
  );
}

export function ListingCard({ listing }: { listing: PublicListing }) {
  const photo = listing.photos[0];
  return (
    <Panel className="tv-mkt-card">
      <div style={{ display: "grid", gap: "0.5rem" }}>
        {/* Photo slot (F1-15's compact strip retired 2026-11-02):
            a photo fills the slot; no photo shows the shared
            gears placeholder (ItemThumb) at the same height, so
            the board grid never stretches cards to the tallest
            row-mate and a photo-less listing still reads as a
            listing, not a gap. */}
        <ItemThumb
          fill
          sizeClass="tv-thumb--mkt tv-thumb-img--contain"
          src={photo?.url ?? null}
          name={listing.title}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "0.6rem",
            alignItems: "baseline",
          }}
        >
          <Link
            to={`/marketplace/${listing.id}`}
            className="tv-mkt-title"
            style={{ fontWeight: 600, fontSize: "1.05rem", color: "var(--text)", textDecoration: "none" }}
          >
            {listing.title}
          </Link>
          <strong className="tv-mkt-price">
            <ListingPrice listing={listing} />
          </strong>
        </div>
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          <Badge tone={listing.listing_type === "wanted" ? "accent" : "neutral"}>
            {listing.listing_type === "wanted" ? "Wanted" : "For sale"}
          </Badge>
          {listing.condition && <Badge tone="neutral">{listing.condition}</Badge>}
          {listing.delivery_ships && <Badge tone="neutral">Ships</Badge>}
          {listing.delivery_local_pickup && (
            <Badge tone="neutral">Local pickup</Badge>
          )}
        </div>
        {(listing.brand || listing.model) && (
          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {[listing.brand, listing.model].filter(Boolean).join(" · ")}
          </span>
        )}
        <span style={{ fontSize: "0.9rem" }}>
          <Link to={`/users/${listing.seller_id}`}>{listing.seller_name}</Link>
          {" · "}
          <span title="Seller rating">{reputationBadge(listing.seller_reputation)}</span>
          {listing.area_label ? ` · ${listing.area_label}` : ""}
        </span>
        {listing.phone && (
          <span style={{ fontSize: "0.9rem" }}>
            Call or text: <a href={`tel:${listing.phone}`}>{listing.phone}</a>
          </span>
        )}
      </div>
    </Panel>
  );
}

/** The contact modal: message the seller about THIS listing —
 *  the thread anchors to it (title snapshot on the thread). */
export function MessageSellerModal({
  listing,
  onClose,
}: {
  listing: PublicListing;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const mine = user?.id === listing.seller_id;
  const verb = listing.listing_type === "wanted" ? "I have this" : "Message seller";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!body.trim()) return;
    setSending(true);
    try {
      const thread = await openThread({
        recipient_id: listing.seller_id,
        body: body.trim(),
        anchor_type: "listing",
        anchor_id: listing.id,
      });
      toast("Message sent — it lands as a request until they reply.", {
        title: "Sent",
        tone: "success",
      });
      onClose();
      navigate(`/messages/${thread.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't send that message.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <Modal open title={`${verb}: ${listing.title}`} onClose={onClose}>
      {mine ? (
        <p style={{ margin: 0 }}>This is your own listing.</p>
      ) : (
        <form
          onSubmit={onSubmit}
          style={{ display: "grid", gap: "0.9rem", minWidth: "min(420px, 80vw)" }}
        >
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Your message goes to {listing.seller_name} about this listing.
            First contact lands as a message request — keep it about the
            deal, and never share payment details outside the site.
          </p>
          <FormField label="Message" htmlFor="mk-contact-body">
            <TextArea
              id="mk-contact-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={4}
              required
            />
          </FormField>
          <div style={{ display: "flex", gap: "0.6rem", justifyContent: "flex-end" }}>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={sending}>
              Send
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function BoardContent({ signedIn }: { signedIn: boolean }) {
  const [listings, setListings] = useState<PublicListing[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [type, setType] = useState("");
  const [area, setArea] = useState("");
  const [sort, setSort] = useState<BoardQuery["sort"]>("newest");

  const load = useCallback(async () => {
    try {
      const query: BoardQuery = {
        q: appliedQ || undefined,
        listing_type: type || undefined,
        area: area || undefined,
        sort,
      };
      setListings(
        signedIn ? await getBoard(query) : await getPublicBoard(query),
      );
      setError("");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't load the board.",
      );
    }
  }, [signedIn, appliedQ, type, area, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          flexWrap: "wrap",
          gap: "0.6rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Tools for sale</h1>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          {signedIn && (
            <>
              <LinkButton to="/marketplace/new">List an item</LinkButton>
              <LinkButton to="/marketplace/mine" variant="secondary">My listings &amp; deals</LinkButton>
            </>
          )}
        </div>
      </div>
      <p style={{ margin: 0, color: "var(--text-muted)" }}>
        Tools for sale and wanted, from members of the community. Anyone
        can browse; Toolbox Vault never handles the money — you and the
        seller arrange payment and pickup between yourselves.
        {!signedIn && (
          <>
            {" "}
            <Link to="/login">Log in</Link> to message a seller or post
            your own.
          </>
        )}
      </p>

      <Panel>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedQ(q.trim());
          }}
          style={{
            display: "flex",
            gap: "0.7rem",
            flexWrap: "wrap",
            alignItems: "end",
          }}
        >
          <div style={{ flex: "2 1 220px" }}>
            <FormField label="Search" htmlFor="mk-q">
              <TextInput
                id="mk-q"
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="Brand, tool, keyword…"
              />
            </FormField>
          </div>
          <div style={{ flex: "1 1 150px" }}>
            <FormField label="Type" htmlFor="mk-type">
              <Select
                id="mk-type"
                value={type}
                onChange={(event) => setType(event.target.value)}
              >
                <option value="">For sale + wanted</option>
                <option value="for_sale">For sale</option>
                <option value="wanted">Wanted</option>
              </Select>
            </FormField>
          </div>
          <div style={{ flex: "1 1 150px" }}>
            <FormField label="Area contains" htmlFor="mk-area">
              <TextInput
                id="mk-area"
                value={area}
                onChange={(event) => setArea(event.target.value)}
                placeholder="City or state"
              />
            </FormField>
          </div>
          <div style={{ flex: "1 1 150px" }}>
            <FormField label="Sort" htmlFor="mk-sort">
              <Select
                id="mk-sort"
                value={sort}
                onChange={(event) =>
                  setSort(event.target.value as BoardQuery["sort"])
                }
              >
                <option value="newest">Newest first</option>
                <option value="price_asc">Price: low to high</option>
                <option value="price_desc">Price: high to low</option>
                <option value="rating">Seller rating</option>
              </Select>
            </FormField>
          </div>
          <Button type="submit" variant="secondary">
            Search
          </Button>
        </form>
      </Panel>

      {error && <Alert tone="danger">{error}</Alert>}
      {listings === null && !error && <Spinner />}
      {listings !== null && listings.length === 0 && (
        <Panel>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Nothing on the board matches. Try a wider search — or be the
            first to list.
          </p>
        </Panel>
      )}
      {listings !== null && listings.length > 0 && (
        <div
          style={{
            display: "grid",
            gap: "1rem",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            alignItems: "start",
          }}
        >
          {listings.map((listing) => (
            <ListingCard key={listing.id} listing={listing} />
          ))}
        </div>
      )}
    </div>
  );
}

export function MarketplaceBoardPage() {
  const { user } = useAuth();
  return <BoardContent signedIn={!!user} />;
}

function ListingDetailContent() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [listing, setListing] = useState<PublicListing | null>(null);
  const [error, setError] = useState("");
  const [contactOpen, setContactOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getPublicListing(id)
      .then((row) => {
        if (!cancelled) setListing(row);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Couldn't load that listing.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
        <Breadcrumbs
          items={[{ label: "Tools for sale", to: "/marketplace" }, { label: "Listing" }]}
        />
        <Alert tone="danger">{error}</Alert>
      </div>
    );
  }
  if (!listing) return <Spinner />;

  const mine = user?.id === listing.seller_id;
  const verb = listing.listing_type === "wanted" ? "I have this" : "Message seller";

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
      <Breadcrumbs
        items={[{ label: "Tools for sale", to: "/marketplace" }, { label: listing.title }]}
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
        <h1 style={{ margin: 0 }}>{listing.title}</h1>
        <strong style={{ fontSize: "1.2rem" }}>
          <ListingPrice listing={listing} />
        </strong>
      </div>

      {listing.photos.length > 0 && (
        <div style={{ display: "flex", gap: "0.7rem", flexWrap: "wrap" }}>
          {listing.photos.map((photo) => (
            <img
              key={photo.url}
              src={photo.url}
              alt={photo.filename}
              style={{
                width: "220px",
                height: "160px",
                objectFit: "cover",
                borderRadius: "var(--radius)",
                border: "1px solid var(--edge)",
              }}
            />
          ))}
        </div>
      )}

      <Panel title="Details">
        <div style={{ display: "grid", gap: "0.45rem" }}>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
            <Badge tone={listing.listing_type === "wanted" ? "accent" : "neutral"}>
              {listing.listing_type === "wanted" ? "Wanted" : "For sale"}
            </Badge>
            {listing.condition && <Badge tone="neutral">{listing.condition}</Badge>}
            {listing.delivery_ships && <Badge tone="neutral">Ships</Badge>}
            {listing.delivery_local_pickup && (
              <Badge tone="neutral">Local pickup</Badge>
            )}
          </div>
          {(listing.brand || listing.model) && (
            <span>
              {[listing.brand, listing.model].filter(Boolean).join(" · ")}
            </span>
          )}
          {listing.description && (
            <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{listing.description}</p>
          )}
          {listing.area_label && <span>Area: {listing.area_label}</span>}
          {listing.phone && (
            <span>
              Call or text: <a href={`tel:${listing.phone}`}>{listing.phone}</a>
            </span>
          )}
        </div>
      </Panel>

      <Panel title="Seller">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "0.6rem",
          }}
        >
          <span>
            <Link to={`/users/${listing.seller_id}`}>{listing.seller_name}</Link>
            {" · "}
            {reputationBadge(listing.seller_reputation)}
            {" · member since "}
            {new Date(listing.seller_member_since).toLocaleDateString()}
          </span>
          {user && !mine && (
            <Button type="button" onClick={() => setContactOpen(true)}>
              {verb}
            </Button>
          )}
          {user && mine && (
            <LinkButton to="/marketplace/mine" variant="secondary">Manage in My listings</LinkButton>
          )}
          {!user && (
            <span style={{ color: "var(--text-muted)" }}>
              <Link to="/login">Log in</Link> to message the seller.
            </span>
          )}
        </div>
      </Panel>

      {contactOpen && (
        <MessageSellerModal listing={listing} onClose={() => setContactOpen(false)} />
      )}
    </div>
  );
}

export function MarketplaceListingPage() {
  return <ListingDetailContent />;
}
