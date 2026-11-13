"""Dealers module tables (item structure package, owner 2026-10-18).

Two layers, per the owner's model:

  COMPANIES — a prefilled platform DIRECTORY (owner_id NULL,
  is_directory: Matco, Snap-on, Mac, Cornwell, ...) any user can see
  and pick from, PLUS private companies a user enters for their own
  records only (owner_id set — never visible to anyone else).

  AGENTS — the independent truck drivers under a company. An agent
  is either a platform user (linked by exact account number only —
  no enumeration) or a PRIVATE record the mechanic typed in
  (private_agents: owner-only, never public). A user's PREFERRED
  agents (preferred_agents) live at the USER level — per user x per
  company, possibly several — and can change at any time.

This module depends on core only. Inventory holds a bare FK to
dealer_companies (the item's dealer TAG) and reads names through a
lazy import; it never depends on this module being enabled.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.modules.dealers.agent_codes import generate_agent_code

from app.core.db import Base


class DealerCompany(Base):
    """A tool company: directory entry or a user's private record."""

    __tablename__ = "dealer_companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = platform directory row (operator-curated). Set = a
    # user's private company, visible to that user only.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Department phone numbers: [{label, number}] — labels like
    # "Customer Service", "Technical Service", "Billing", or a
    # general number. ONLY publicly listed corporate data goes in
    # directory rows (seeded from the companies' official sites).
    phones: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_directory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Corporate directory data (2026-10-19): warranty-service facts
    # for the big tool brands, researched from OFFICIAL brand sources
    # only (see goals/.../files/corporate-directory-data.json). These
    # fields carry a strict discipline:
    #   - ship_to_* is set ONLY when the brand officially publishes
    #     the address FOR warranty/repair mail-in. A headquarters or
    #     contact address NEVER goes here (it stays in `address`).
    #   - ship_to_scope "scoped" means the address serves only the
    #     slice named in ship_to_scope_note (e.g. torque products
    #     only) — the UI must render the scope WITH the address.
    #   - Brands with no mail-in route have ship_to_* NULL and a
    #     warranty_process gate instead (call first / form first /
    #     photo claim / return to store). The UI shows the gate,
    #     never an address.
    #   - logo_key is an object-storage key under platform/logos/,
    #     harvested from the brand's own site; NULL = render the
    #     text tile, never a substitute logo.
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manufacturer", server_default="manufacturer"
    )
    warranty_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    # The brand's OFFICIAL flyer document address (flyers module,
    # 2026-11-06): a direct flyer PDF the brand publishes on its
    # own site, kept BY THE PLATFORM (researched + verified
    # operator data, the corporate-directory discipline — never
    # a specials web page, which the flyer pull cannot fetch).
    # The flyers daily pull posts whatever this address holds
    # under the company's flyer spot — unless a poster for that
    # company set the spot's own standing address, which wins.
    official_flyer_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    # A warranty-specific line when the brand publishes one that
    # genuinely differs from customer service (Harbor Freight's
    # 24/7 ESP line, Sunex's service line). NULL otherwise — the
    # department numbers live in `phones`.
    warranty_phone: Mapped[str | None] = mapped_column(String(100))
    ship_to_name: Mapped[str | None] = mapped_column(String(300))
    ship_to_address: Mapped[str | None] = mapped_column(Text)
    # general | scoped (see ship_to_scope_note); NULL when no ship-to.
    ship_to_scope: Mapped[str | None] = mapped_column(String(20))
    ship_to_scope_note: Mapped[str | None] = mapped_column(Text)
    # {"gate": str|None, "notes": [str]} — the gate is the required
    # first step for brands with no mail-in address; notes are the
    # researched process facts shown as a short list.
    warranty_process: Mapped[dict | None] = mapped_column(JSONB)
    logo_key: Mapped[str | None] = mapped_column(String(500))
    # Logo tile presentation: NULL = the standard neutral tile.
    # "dark" for logos that are white/light glyphs on transparency
    # (Mac Tools, Astro Pneumatic) — invisible on a light tile, so
    # the UI renders those on a dark tile in every theme instead.
    logo_tile: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PrivateAgent(Base):
    """A dealer agent in ONE user's own records — a name and number
    they typed in (or picked from their phone contacts). Never
    public, never shared, never listed anywhere."""

    __tablename__ = "private_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    phone: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The agent record (owner model, 2026-11-04 — stage 1): the
    # app's five fields are name/phone/email/location/notes;
    # `location` is the ROUTE AREA in the app's own word (free
    # text — "Brainerd / Baxter area"). The site adds the ROUTE
    # SCHEDULE on the record — the same triple AgentProfile
    # carries (frequency + weekday + anchor), computed by the
    # same route_days module; all NULL = no route (the form's
    # "N/A"). TENURE is the app's started_at / ended_at pair,
    # day-granular: when this agent started (and stopped) being
    # one of the owner's agents for his route. Switching the
    # preferred stamps them; the owner can also type the real
    # dates by hand.
    location: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    route_frequency: Mapped[str | None] = mapped_column(String(20))
    route_day_of_week: Mapped[int | None] = mapped_column(Integer)
    route_anchor_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[date | None] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date)
    # Private -> platform switch (dealer portal, 2026-10-19): when the
    # owner links this record to a real Toolbox Vault account, the
    # record is ARCHIVED (kept, hidden from the working lists) and the
    # owner's preference rows re-point at the platform user. Nothing
    # is deleted and nothing is auto-matched — the owner typed the
    # exact account number. Unlinking restores the record and, via
    # link_snapshot, the exact preference rows it fed.
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # NO ondelete on purpose, same posture as the owner FK: the
    # account-deletion cascade severs links explicitly (and rotates
    # the agent code on takeover links) instead of letting the
    # database quietly drop them.
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    # Agent code + takeover link (owner model, 2026-11-03): every
    # record carries a unique, human-shareable code (agent_codes
    # module) the owner can hand to the real-world agent. When
    # that agent signs up, enters the code and the owner accepts
    # the takeover request, linked_user_id points at their account
    # with link_source "takeover" — the record STAYS the working
    # record (claims, truck accounts and route facts reference IT,
    # so the agent inherits all of them in place). link_source
    # "switch" marks the older account-number switch (which
    # archives the record); NULL means unlinked.
    agent_code: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        unique=True,
        index=True,
        default=generate_agent_code,
    )
    link_source: Mapped[str | None] = mapped_column(String(20))
    # [{company_id}] — every preference row that pointed at this
    # record at link time, so unlink can restore them losslessly.
    link_snapshot: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    # 30-day invite reminder (owner order, 2026-11-07): the stamp
    # the daily sweep writes in the same commit as the ONE inbox
    # reminder that a still-unclaimed record has sat for 30 days
    # — invite your agent to join the network. NULL = never
    # reminded. The marker lives on the record itself (the
    # claims backorder_last_reminded_at pattern): a re-run is a
    # no-op by construction, an owner deleting the inbox note
    # cannot resurrect a second reminder, and a record deleted
    # before day 30 takes the marker with it — no residue.
    invite_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentTakeoverRequest(Base):
    """One agent's ask to take over one private agent record
    (owner model, 2026-11-03). Created when a signed-in user
    enters the record's agent code; the record's OWNER accepts or
    declines. Accepting links the record to the requester's
    account (link_source "takeover") — the record itself, and
    everything referencing it, becomes the agent's working seat
    for that customer. Both FKs CASCADE: the row is meaningless
    without its record, and a request made BY a deleted account
    dies with it (the deletion cascade also removes these
    explicitly, belt and braces)."""

    __tablename__ = "agent_takeover_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    private_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # pending | accepted | declined | superseded (closed because
    # another request for the same record was accepted first)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PreferredAgent(Base):
    """One CONNECTION between a user and an agent for a company
    (owner model, 2026-11-04 — stage 1): this user is connected
    with this agent for this company. The agent is EITHER a
    platform user (agent_user_id) OR one of the user's private
    records (private_agent_id) — the CHECK keeps exactly one.
    Several rows per (user, company) are the ROSTER: every agent
    the user has connected with stays listed. ANY number of rows
    per (user, company) may carry is_preferred (multi-preferred,
    owner ruling 2026-11-05): a starred agent is a preferred
    agent — the user may work several agents at one dealer,
    each with his own claims and truck account. FUNCTIONAL
    defaults that need ONE agent (a new claim's default seat,
    the truck-account holder resolution, the wizard's charge
    agent) resolve to the EARLIEST preferred through
    claims.agent_on_record / preferred_row_for, and to the
    earliest connection when none is starred. SUMMARY
    displays of "the preferred agent" (the dealer list row,
    the item pages' agent line, the Warranty tab's agent row)
    instead read preferred_summary_view (owner ruling
    2026-11-06): one flagged names him; several flagged
    shows "Multiple Agents" and names nobody. Before stage 1 every row was a "preference"
    and the earliest silently won; stage 1 made exactly one
    flag explicit, and migration 0075 flagged the earliest row
    per pair (the old resolution) so nothing moved in the
    changeover.

    A platform agent's TENURE for this customer lives on the
    row (tenure_started_at / tenure_ended_at): tenure is
    per-customer, so it can't live on the agent's account the
    way a private record carries its own pair. Tenure tracks
    the CONNECTION (stamped when the row is created), never
    the star: flagging or unflagging an agent moves no dates."""

    __tablename__ = "preferred_agents"
    __table_args__ = (
        CheckConstraint(
            "(agent_user_id IS NULL) <> (private_agent_id IS NULL)",
            name="ck_preferred_agents_exactly_one_agent",
        ),
        UniqueConstraint(
            "user_id", "company_id", "agent_user_id",
            name="uq_preferred_agents_platform_agent",
        ),
        UniqueConstraint(
            "user_id", "company_id", "private_agent_id",
            name="uq_preferred_agents_private_agent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="CASCADE"),
    )
    # Provenance for the private -> platform switch: set when this
    # row was re-pointed from a private record to the platform user,
    # so unlinking that record can flip exactly these rows back.
    switched_from_private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="SET NULL"),
    )
    # The preferred flag: ANY number of rows per (user,
    # company) may be true (multi-preferred, 2026-11-05) — the
    # service's flag endpoint sets it per agent, independently;
    # no database constraint ever limited it to one.
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Platform-side tenure for this customer (see the class
    # docstring). Private records carry their own pair instead;
    # these stay NULL on private rows.
    tenure_started_at: Mapped[date | None] = mapped_column(Date)
    tenure_ended_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentProfile(Base):
    """A dealer-group user's public-facing agent profile (dealer
    portal, 2026-10-19). 1:1 with the user. Everything here is the
    agent's OWN choice: the contact fields are what they typed for
    public display — the account email/phone never fall back in.

    Visibility (owner spec): publicly_listed DEFAULTS OFF. Only a
    listed profile that REPRESENTS a directory company appears on
    that company's page. The photo rides the shared attachment
    machinery's rules (photo kind, presigned flow); only the storage
    key is kept, read URLs are minted at serialize time.
    """

    __tablename__ = "dealer_agent_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    service_area: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    photo_key: Mapped[str | None] = mapped_column(String(500))
    publicly_listed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Service-area geometry (dealer build, 2026-10-20 — owner
    # design 07:38: drawn territory preferred, ZIP + radius the
    # blunt fallback). `service_area` above stays the human label;
    # these columns are the MACHINE shape Find-an-Agent matches on:
    #   area_type "polygon": area_polygon is a GeoJSON Polygon
    #     ({"type": "Polygon", "coordinates": [[[lng, lat], ...]]},
    #     any shape/size the agent drew — never constrained to a
    #     circle or box).
    #   area_type "radius": area_center_lat/lng + area_radius_km
    #     (+ area_zip, the ZIP the center was resolved from).
    #   area_type NULL: no area defined — and publicly_listed may
    #     not be enabled without one (portal.update_profile rules).
    area_type: Mapped[str | None] = mapped_column(String(20))
    area_polygon: Mapped[dict | None] = mapped_column(JSONB)
    area_center_lat: Mapped[float | None] = mapped_column(Float)
    area_center_lng: Mapped[float | None] = mapped_column(Float)
    area_radius_km: Mapped[float | None] = mapped_column(Float)
    area_zip: Mapped[str] = mapped_column(
        String(10), nullable=False, default="", server_default=""
    )
    # Route schedule (completeness audit A2, 2026-10-22): the
    # agent's fixed route — frequency + weekday + the anchor date
    # the biweekly/monthly cycles count from (the app carried
    # these; migration data needs a home). All NULL = no route.
    route_frequency: Mapped[str | None] = mapped_column(String(20))
    route_day_of_week: Mapped[int | None] = mapped_column(Integer)
    route_anchor_date: Mapped[date | None] = mapped_column(Date)
    # Stripe Connect seam (wave 2, 2026-10-20): written ONLY by
    # the truck_payments dark seam when it activates — the
    # connected account id + Stripe's charges/payouts verdicts +
    # where onboarding stands. All inert until platform keys +
    # the payments.connect_enabled switch exist.
    stripe_connect_account_id: Mapped[str | None] = mapped_column(String(100))
    connect_charges_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    connect_payouts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    connect_onboarding_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_started",
        server_default="not_started",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CompanyRepresentation(Base):
    """An agent's claim "I run a truck for THIS directory company".

    Self-asserted links are UNVERIFIED until an operator verifies
    them (Admin -> Dealer directory -> Representations). Only
    DIRECTORY companies can be represented — a private company is
    one user's own record and has no public page to appear on.
    """

    __tablename__ = "dealer_company_representations"
    __table_args__ = (
        UniqueConstraint(
            "agent_user_id", "company_id",
            name="uq_representations_agent_company",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GeocodeCache(Base):
    """One resolved place per normalized query (platform data —
    no owner). Find-an-Agent geocodes ZIP/city/address text before
    matching areas; ZIPs resolve from the bundled centroid dataset
    (data/us_zip_centroids.csv, GeoNames CC BY 4.0) and everything
    else from Nominatim, and BOTH land here so a place is only ever
    looked up once. Rows never expire in v1: place centroids do not
    move, and a stale display name is a cosmetic risk only."""

    __tablename__ = "geocode_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Normalized query (casefolded, whitespace-collapsed) — the
    # lookup key; the raw text is kept for debugging only.
    query_key: Mapped[str] = mapped_column(
        String(300), nullable=False, unique=True, index=True
    )
    query_text: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # dataset | nominatim — where the answer came from.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DealerListHidden(Base):
    """One row = this user removed this DIRECTORY company from
    their own dealer pick list (owner directive, 2026-10-31:
    "Users should be able to add or remove default dealer lists").

    The customization is an OVERLAY, never a copy: the pick list
    is computed as (the live directory MINUS these rows) plus the
    user's own additions, so a brand the operator adds to the
    directory later appears for everyone who hasn't hidden it,
    and hiding never touches the directory row itself, the user's
    items tagged with it, or anyone else's list."""

    __tablename__ = "user_dealer_list_hidden"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "company_id", name="uq_dealer_list_hidden_user_company"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DealerListEntry(Base):
    """One of the user's OWN additions to their dealer pick list
    (owner directive, 2026-10-31): a lightweight dealer template —
    name plus the same basics the Add Dealer wizard's first step
    collects — that sits in the pick list beside the directory
    brands. It is NOT a dealer record: picking it in an entry flow
    CREATES the user's private company from these fields (the
    created_company_id link), after which the company itself is
    the record and the entry is spent. Removing an entry never
    touches a company it created."""

    __tablename__ = "user_dealer_list_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manufacturer",
        server_default="manufacturer",
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phones: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The private company this entry created when first picked;
    # SET NULL so deleting that company makes the entry pickable
    # again instead of pointing at a ghost.
    created_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DealerCompanyPersonalEdit(Base):
    """One user's PERSONAL details for a DIRECTORY company
    (owner, 2026-11-05: "there is no way to edit a dealer" —
    his fix: personal edits).

    A field-level OVERLAY, never a copy — the same family as
    the dealer-list overlay pair (DealerListHidden /
    DealerListEntry). Every column is NULLABLE and NULL means
    "no override": the read seam starts from the live directory
    row and replaces exactly the fields this user changed, so
    an operator's directory update flows through to every field
    the user did NOT touch, and saving a field back to the
    directory value drops its override (a row with no overrides
    left is deleted — no row). The directory row itself and
    every other user's view stay untouched.

    Only the company's identity/contact fields can be
    overridden (name, email, website, address, phones, notes,
    logo). The corporate warranty block (kind, warranty_url,
    ship_to_*, warranty_process) is researched platform data
    under its own discipline on DealerCompany and is NOT
    overlayable — it stays directory truth for everyone. For
    logo_key / logo_tile an override of "" means the user
    explicitly cleared the value (blank logo / standard tile);
    NULL still means no override.

    The user FK carries NO cascade on purpose (the
    DealerListHidden posture): the account-deletion cascade
    clears these rows explicitly, so account deletion is a
    deliberate act, not a side effect. The company FK
    CASCADEs: an operator deleting a directory company takes
    its personal layers with it."""

    __tablename__ = "user_dealer_company_edits"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "company_id", name="uq_dealer_company_edits_user_company"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    website: Mapped[str | None] = mapped_column(String(500))
    address: Mapped[str | None] = mapped_column(Text)
    phones: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    logo_key: Mapped[str | None] = mapped_column(String(500))
    logo_tile: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Warranty service request statuses. The flow: a send lands
# UNCLAIMED in the routed agents' incoming queues; the first to
# claim owns it (RECEIVED); the owner works it IN_PROCESS and
# closes it RESOLVED. A claimer who deletes their account sends
# the request back to UNCLAIMED (re-routed) — never stranded.
WR_UNCLAIMED = "unclaimed"
WR_RECEIVED = "received"
WR_IN_PROCESS = "in_process"
WR_RESOLVED = "resolved"
WR_OPEN_STATUSES = (WR_UNCLAIMED, WR_RECEIVED, WR_IN_PROCESS)


class WarrantyServiceRequest(Base):
    """A broken item sent to its dealer for warranty service
    (dealer build, 2026-10-20 — owner design 07:43).

    Created from the maintenance repair flow when the item's
    dealer company has REGISTERED agents. Everything the dealer
    needs is SNAPSHOTTED at send time (the repair-record doctrine:
    the request must stay readable even if the item is later
    renamed, and even if the requester deletes their account —
    that case tombstones the requester fields, forum-style, and
    blanks the contact snapshots: account deletion stays final).

    The item link (item_kind/item_id) and claim_id are PLAIN
    columns, no FKs — the borrowing-ledger pattern: module tables
    never hard-depend on each other's rows. (claim_id pointed at
    the repair record until the repairs ∪ claims merge,
    2026-11-04; migration 0074 renamed the column and re-pointed
    it at the converted claims.)
    """

    __tablename__ = "warranty_service_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # PLAIN column (no FK) by design: the request survives its
    # requester's account deletion as a "Former member" tombstone
    # (the forum two-party-history doctrine — an FK here would
    # make the user's row undeletable on Postgres).
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # SET NULL on company delete; company_name below keeps the
    # request readable (the dealer-delete doctrine: names stay).
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Item snapshot (what the dealer was told).
    item_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    serials: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    purchase_date: Mapped[date | None] = mapped_column(Date)
    warranty_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )
    # Requester snapshot (exactly the payload the send preview
    # showed the requester before they confirmed).
    requester_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    requester_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    requester_phone: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    requester_area: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Routing: the agent user ids this request was offered to at
    # send (preferred agents, else area-covering representatives).
    # Recomputed when a claimer deletes their account.
    routed_agent_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    claimed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WR_UNCLAIMED, index=True
    )
    # Requester deleted their account: the request tombstones for
    # the dealer (contact snapshots blanked by the cascade).
    requester_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
