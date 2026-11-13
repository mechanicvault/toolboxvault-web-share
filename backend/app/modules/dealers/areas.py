"""Service areas + Find-an-Agent (dealer build, 2026-10-20).

Owner design (2026-10-20 07:38): an agent's territory is real
geometry, set on their dealer profile — a FREEFORM POLYGON drawn
on a map (any shape or size, never reduced to a circle or a box),
or the blunt fallback: a ZIP code plus a radius, where the user
confirms specifics with the dealer themselves. Overlapping
territories are NORMAL and expected: a search lists EVERY agent
whose area covers the point — the system never picks a winner or
pretends territories are exclusive.

Matching is plain math on purpose (ray casting + haversine): the
agent counts this serves are in the hundreds-to-thousands, and no
PostGIS dependency is worth taking for it.

Geocoding: a ZIP resolves from the bundled centroid dataset
(data/us_zip_centroids.csv — GeoNames postal data, CC BY 4.0);
anything else (city, address) goes to Nominatim with a polite
user agent and a 1-request-per-second courtesy pace. Every
resolution lands in geocode_cache, so each distinct place is only
ever looked up once, dataset or network.
"""

import csv
import math
import re
import threading
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.modules.core import models as core_models
from app.modules.dealers import models, service

# NOTE: `portal` is imported lazily inside functions below — the
# portal service imports this module for area validation, and the
# two stay decoupled at module load time.

MILES_PER_KM = 0.621371
MIN_RADIUS_MILES = 1.0
MAX_RADIUS_MILES = 500.0
MAX_POLYGON_POINTS = 500

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_UA = "ToolboxVault/1.0 (dealer agent directory search)"
_NOMINATIM_TIMEOUT = 5.0
_nominatim_lock = threading.Lock()
_nominatim_last_call = 0.0

_ZIP_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")

# -- bundled ZIP centroids ---------------------------------------------------

_zip_rows: dict[str, tuple[str, str, float, float]] | None = None


def _load_zips() -> dict[str, tuple[str, str, float, float]]:
    """zip -> (place, state, lat, lng), loaded once per process
    from the bundled GeoNames extract."""
    global _zip_rows
    if _zip_rows is None:
        rows: dict[str, tuple[str, str, float, float]] = {}
        path = Path(__file__).parent / "data" / "us_zip_centroids.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#"):
                    continue
                for row in csv.reader([line]):
                    if len(row) != 5 or row[0] == "zip":
                        continue
                    try:
                        rows[row[0]] = (
                            row[1], row[2], float(row[3]), float(row[4])
                        )
                    except ValueError:
                        continue
        _zip_rows = rows
    return _zip_rows


def zip_centroid(zip_code: str) -> tuple[str, str, float, float] | None:
    """(place, state, lat, lng) for a 5-digit ZIP, or None."""
    match = _ZIP_RE.match(zip_code or "")
    if not match:
        return None
    return _load_zips().get(match.group(1))


# -- geometry ------------------------------------------------------------------


def point_in_polygon(lat: float, lng: float, ring: list) -> bool:
    """Ray casting over a GeoJSON ring of [lng, lat] pairs. The
    ring may or may not repeat its first point at the end; both
    shapes are handled."""
    points = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
    if len(points) < 3:
        return False
    inside = False
    x, y = lng, lat
    previous = points[-1]
    for current in points:
        xi, yi = current
        xj, yj = previous
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at_y:
                inside = not inside
        previous = current
    return inside


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def profile_has_area(profile: models.AgentProfile | None) -> bool:
    if profile is None:
        return False
    if profile.area_type == "polygon":
        return bool(profile.area_polygon)
    if profile.area_type == "radius":
        return (
            profile.area_center_lat is not None
            and profile.area_center_lng is not None
            and profile.area_radius_km is not None
        )
    return False


def profile_covers_point(
    profile: models.AgentProfile, lat: float, lng: float
) -> bool:
    if profile.area_type == "polygon" and profile.area_polygon:
        ring = (profile.area_polygon.get("coordinates") or [[]])[0]
        return point_in_polygon(lat, lng, ring)
    if (
        profile.area_type == "radius"
        and profile.area_center_lat is not None
        and profile.area_center_lng is not None
        and profile.area_radius_km is not None
    ):
        return (
            haversine_km(
                lat, lng, profile.area_center_lat, profile.area_center_lng
            )
            <= profile.area_radius_km
        )
    return False


def area_summary(profile: models.AgentProfile | None) -> dict:
    """The profile's area in wire shape (owner view): the geometry
    plus the miles reading of a radius (the unit agents think in;
    kilometers are the storage unit)."""
    if profile is None or not profile_has_area(profile):
        return {
            "area_type": None,
            "area_polygon": None,
            "area_center_lat": None,
            "area_center_lng": None,
            "area_radius_miles": None,
            "area_zip": "",
        }
    return {
        "area_type": profile.area_type,
        "area_polygon": profile.area_polygon,
        "area_center_lat": profile.area_center_lat,
        "area_center_lng": profile.area_center_lng,
        "area_radius_miles": (
            round(profile.area_radius_km * MILES_PER_KM * 1000) / 1000
            if profile.area_radius_km is not None
            else None
        ),
        "area_zip": profile.area_zip or "",
    }


def validate_area(data: dict) -> dict:
    """Clean an area payload from the profile write into model
    fields. `area_type` None clears the area entirely. Raises
    DealerError with friendly copy on anything unusable — a
    territory the matcher can't read is worse than none."""
    area_type = data.get("area_type")
    if area_type is None:
        return {
            "area_type": None,
            "area_polygon": None,
            "area_center_lat": None,
            "area_center_lng": None,
            "area_radius_km": None,
            "area_zip": "",
        }
    if area_type == "polygon":
        polygon = data.get("area_polygon")
        ring = None
        if isinstance(polygon, dict):
            coords = polygon.get("coordinates")
            if isinstance(coords, list) and coords and isinstance(coords[0], list):
                ring = coords[0]
        if not ring:
            raise service.DealerError(
                "Draw your territory on the map — a shape with at least 3 points."
            )
        points: list[list[float]] = []
        for raw in ring:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                raise service.DealerError("That territory shape isn't readable.")
            try:
                lng, lat = float(raw[0]), float(raw[1])
            except (TypeError, ValueError):
                raise service.DealerError("That territory shape isn't readable.")
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
                raise service.DealerError(
                    "Territory points must be real places on the map."
                )
            points.append([lng, lat])
        # Drop a duplicated closing point for the distinct count,
        # then re-close the ring for storage.
        distinct = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
        if len({(p[0], p[1]) for p in distinct}) < 3:
            raise service.DealerError(
                "A territory needs at least 3 different points."
            )
        if len(points) > MAX_POLYGON_POINTS:
            raise service.DealerError(
                f"That territory has too many points (max {MAX_POLYGON_POINTS})."
            )
        if points[0] != points[-1]:
            points.append(list(points[0]))
        return {
            "area_type": "polygon",
            "area_polygon": {"type": "Polygon", "coordinates": [points]},
            "area_center_lat": None,
            "area_center_lng": None,
            "area_radius_km": None,
            "area_zip": "",
        }
    if area_type == "radius":
        lat = data.get("area_center_lat")
        lng = data.get("area_center_lng")
        miles = data.get("area_radius_miles")
        try:
            lat_f, lng_f, miles_f = float(lat), float(lng), float(miles)
        except (TypeError, ValueError):
            raise service.DealerError(
                "A radius area needs a ZIP code and a radius in miles."
            )
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
            raise service.DealerError("That ZIP code doesn't resolve to a place.")
        if not (MIN_RADIUS_MILES <= miles_f <= MAX_RADIUS_MILES):
            raise service.DealerError(
                f"Radius must be between {MIN_RADIUS_MILES:g} and "
                f"{MAX_RADIUS_MILES:g} miles."
            )
        zip_code = str(data.get("area_zip") or "").strip()
        return {
            "area_type": "radius",
            "area_polygon": None,
            "area_center_lat": lat_f,
            "area_center_lng": lng_f,
            "area_radius_km": miles_f / MILES_PER_KM,
            "area_zip": zip_code[:10],
        }
    raise service.DealerError("Area type must be 'polygon' or 'radius'.")


# -- geocoding -------------------------------------------------------------------


def _normalize_query(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def _nominatim_lookup(query: str) -> tuple[float, float, str] | None:
    """One Nominatim search, paced politely (their usage policy
    asks for <= 1 req/s; the cache makes repeats free, so the
    pace only ever bites on genuinely new places)."""
    global _nominatim_last_call
    with _nominatim_lock:
        wait = 1.05 - (time.monotonic() - _nominatim_last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            response = httpx.get(
                _NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers={"User-Agent": _NOMINATIM_UA},
                timeout=_NOMINATIM_TIMEOUT,
            )
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            _nominatim_last_call = time.monotonic()
    if not results:
        return None
    first = results[0]
    try:
        return (
            float(first["lat"]),
            float(first["lon"]),
            str(first.get("display_name") or query),
        )
    except (KeyError, TypeError, ValueError):
        return None


def geocode(db: Session, query: str) -> dict | None:
    """Resolve ZIP / city / address text to a point, or None when
    the place can't be found. Cache-first; ZIPs resolve from the
    bundled dataset without touching the network."""
    text = " ".join(str(query or "").split())
    if not text:
        return None
    key = _normalize_query(text)
    cached = (
        db.query(models.GeocodeCache)
        .filter(models.GeocodeCache.query_key == key)
        .first()
    )
    if cached is not None:
        return {
            "lat": cached.lat,
            "lng": cached.lng,
            "display_name": cached.display_name,
            "source": cached.source,
        }
    found: tuple[float, float, str] | None = None
    source = ""
    zip_hit = zip_centroid(text)
    if zip_hit is not None:
        place, state, lat, lng = zip_hit
        found = (lat, lng, f"{place}, {state} {text.strip()[:5]}")
        source = "dataset"
    else:
        found = _nominatim_lookup(text)
        source = "nominatim"
    if found is None:
        return None
    lat, lng, display = found
    row = models.GeocodeCache(
        query_key=key,
        query_text=text[:300],
        lat=lat,
        lng=lng,
        display_name=display[:300],
        source=source,
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        # A concurrent resolve of the same place won the unique
        # key — its row is just as good.
        db.rollback()
    return {"lat": lat, "lng": lng, "display_name": display, "source": source}


# -- Find an Agent -----------------------------------------------------------------


def _agent_companies(db: Session, agent_user_id: uuid.UUID) -> list[dict]:
    """The directory companies this agent represents, with the
    verified flag — the badges ride along so a search result can
    show which of their companies they're confirmed for."""
    from app.modules.dealers import portal

    out = []
    for rep in portal.list_representations(db, agent_user_id):
        company = db.get(models.DealerCompany, rep.company_id)
        if company is None or not company.is_directory:
            continue
        out.append(
            {
                "company_id": company.id,
                "company_name": company.name,
                "verified": bool(rep.verified),
            }
        )
    out.sort(key=lambda c: c["company_name"].lower())
    return out


def find_agent_card(
    db: Session,
    user: core_models.User,
    profile: models.AgentProfile,
    *,
    public: bool,
) -> dict:
    """One Find-an-Agent result. The signed-in card carries the
    agent's published contact fields (only the ones they filled)
    and their companies; the anonymous card is the same identity
    minus contact actions — reading is public, contacting takes
    an account (the marketplace board's posture)."""
    from app.modules.dealers import portal

    companies = _agent_companies(db, user.id)
    card: dict = {
        "agent_user_id": user.id,
        "display_name": profile.display_name or user.name,
        "service_area": profile.service_area or "",
        "area_type": profile.area_type,
        "verified": any(c["verified"] for c in companies),
        "companies": companies,
    }
    photo_url = portal._photo_thumb_url(profile.photo_key)
    if photo_url:
        card["photo_url"] = photo_url
    if not public:
        if profile.phone:
            card["phone"] = profile.phone
        if profile.contact_email:
            card["contact_email"] = profile.contact_email
    return card


def search_agents(
    db: Session,
    *,
    lat: float,
    lng: float,
    company_id: uuid.UUID | None = None,
    public: bool = False,
) -> list[dict]:
    """Every publicly listed agent whose territory covers the
    point — overlaps included, everyone shown. Optionally narrowed
    to agents representing one directory company. Order: verified
    (for any company) first, then name."""
    profiles = (
        db.query(models.AgentProfile)
        .filter(models.AgentProfile.publicly_listed.is_(True))
        .all()
    )
    cards = []
    for profile in profiles:
        if not profile_covers_point(profile, lat, lng):
            continue
        user = db.get(core_models.User, profile.user_id)
        if user is None or not user.is_active:
            continue
        card = find_agent_card(db, user, profile, public=public)
        if company_id is not None and not any(
            c["company_id"] == company_id for c in card["companies"]
        ):
            continue
        cards.append(card)
    cards.sort(key=lambda c: (not c["verified"], c["display_name"].lower()))
    return cards


def find_agents(
    db: Session,
    query: str,
    *,
    company_id: uuid.UUID | None = None,
    public: bool = False,
) -> dict | None:
    """Geocode + search in one call. None = the place itself
    couldn't be resolved (the route answers 422 — an honest
    'we couldn't find that place', distinct from 'no agents')."""
    point = geocode(db, query)
    if point is None:
        return None
    return {
        "query": query,
        "point": {
            "lat": point["lat"],
            "lng": point["lng"],
            "display_name": point["display_name"],
        },
        "results": search_agents(
            db,
            lat=point["lat"],
            lng=point["lng"],
            company_id=company_id,
            public=public,
        ),
    }


# -- Find local Agent (stage 3, 2026-11-05) -----------------------------------
#
# The owner-ruled member search (2026-11-04 20:16): ZIP + radius,
# reusable site-wide — the dealer Agents tab mounts it scoped,
# the Find an Agent page mounts it unscoped. Where find_agents
# above answers "whose territory covers this point", this answers
# "whose territory lies at or within R miles of this ZIP": the
# distance is measured to the NEAREST point of the agent's
# territory (0 when the territory covers the ZIP itself).
#
# Findability is stricter than the public window, because a
# connect hangs off every result: a publicly listed profile WITH
# a defined service area AND at least one VERIFIED
# representation. The companies on the card are the verified ones
# only — those are the companies a connect can attach to.

_EARTH_RADIUS_MILES = 3958.7613


def _project_miles(
    lat: float, lng: float, origin_lat: float, origin_lng: float
) -> tuple[float, float]:
    """Local equirectangular projection around the origin, in
    miles. Honest to ~0.1 mi at territory scales (tens of miles);
    territories are route areas, not survey lines."""
    x = (
        math.radians(lng - origin_lng)
        * math.cos(math.radians(origin_lat))
        * _EARTH_RADIUS_MILES
    )
    y = math.radians(lat - origin_lat) * _EARTH_RADIUS_MILES
    return x, y


def _segment_distance_miles(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_area_miles(
    profile: models.AgentProfile, lat: float, lng: float
) -> float | None:
    """Miles from the point to the nearest point of the agent's
    territory; 0.0 when the territory covers the point; None when
    the profile defines no area."""
    if not profile_has_area(profile):
        return None
    if profile_covers_point(profile, lat, lng):
        return 0.0
    if profile.area_type == "radius":
        center_miles = (
            haversine_km(
                lat, lng, profile.area_center_lat, profile.area_center_lng
            )
            * MILES_PER_KM
        )
        return max(0.0, center_miles - profile.area_radius_km * MILES_PER_KM)
    if profile.area_type == "polygon" and profile.area_polygon:
        ring = (profile.area_polygon.get("coordinates") or [[]])[0]
        # GeoJSON points are [lng, lat]; project each vertex into
        # the local mile plane around the search point (which sits
        # at the origin) and take the nearest edge.
        projected = [
            _project_miles(float(p[1]), float(p[0]), lat, lng)
            for p in ring
            if len(p) >= 2
        ]
        if len(projected) < 2:
            return None
        best = math.inf
        for index, (ax, ay) in enumerate(projected):
            bx, by = projected[(index + 1) % len(projected)]
            best = min(best, _segment_distance_miles(0.0, 0.0, ax, ay, bx, by))
        return best
    return None


def local_agent_card(
    db: Session,
    viewer_id: uuid.UUID,
    user: core_models.User,
    profile: models.AgentProfile,
    *,
    distance_miles: float,
) -> dict:
    """One Find local Agent result: the signed-in find-agent card
    narrowed to the agent's VERIFIED companies, each carrying the
    viewer's connection state for it, plus the distance facts."""
    card = find_agent_card(db, user, profile, public=False)
    connections = {
        row.company_id: row
        for row in db.query(models.PreferredAgent)
        .filter(
            models.PreferredAgent.user_id == viewer_id,
            models.PreferredAgent.agent_user_id == user.id,
        )
        .all()
    }
    # The viewer's own names for these dealers (personal edits,
    # 2026-11-05): the card speaks to the signed-in viewer.
    viewer_names = service.personal_name_map(
        db, viewer_id, [c["company_id"] for c in card["companies"]]
    )
    companies = []
    for company in card["companies"]:
        if not company["verified"]:
            continue
        row = connections.get(company["company_id"])
        companies.append(
            {
                **company,
                "company_name": viewer_names.get(
                    company["company_id"], company["company_name"]
                ),
                "connected": row is not None,
                "is_preferred": bool(row.is_preferred) if row else False,
            }
        )
    card["companies"] = companies
    card["verified"] = bool(companies)
    card["distance_miles"] = round(distance_miles, 1)
    card["covers_zip"] = distance_miles <= 0.0
    return card


def search_local_agents(
    db: Session,
    viewer_id: uuid.UUID,
    *,
    zip_code: str,
    radius_miles: float,
    company_id: uuid.UUID | None = None,
) -> dict | None:
    """Every findable registered agent whose territory lies within
    `radius_miles` of the ZIP, nearest first. Optionally narrowed
    to agents with a VERIFIED representation of one company.
    The viewer never finds themselves (connecting to yourself is
    refused everywhere; listing yourself would be noise).
    None = the ZIP itself isn't in the bundled centroid dataset
    (the route answers 422 — distinct from 'no agents')."""
    hit = zip_centroid(zip_code)
    if hit is None:
        return None
    place, state, lat, lng = hit
    zip5 = _ZIP_RE.match(zip_code or "").group(1)  # type: ignore[union-attr]
    profiles = (
        db.query(models.AgentProfile)
        .filter(models.AgentProfile.publicly_listed.is_(True))
        .all()
    )
    cards = []
    for profile in profiles:
        if profile.user_id == viewer_id:
            continue
        distance = distance_to_area_miles(profile, lat, lng)
        if distance is None or distance > radius_miles:
            continue
        user = db.get(core_models.User, profile.user_id)
        if user is None or not user.is_active:
            continue
        card = local_agent_card(
            db, viewer_id, user, profile, distance_miles=distance
        )
        if not card["companies"]:
            continue
        if company_id is not None and not any(
            c["company_id"] == company_id for c in card["companies"]
        ):
            continue
        cards.append(card)
    cards.sort(key=lambda c: (c["distance_miles"], c["display_name"].lower()))
    return {
        "zip": zip5,
        "radius_miles": radius_miles,
        "point": {
            "lat": lat,
            "lng": lng,
            "display_name": f"{place}, {state} {zip5}",
        },
        "results": cards,
    }


# -- Dealers near you (dashboard widget, widget wave 2, 2026-11-10) ----------

_ZIP_IN_TEXT = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_ZIP = re.compile(r"\b[A-Z]{2}\s+(\d{5})(?:-\d{4})?\b")


def _viewer_zip(postal_address: str) -> str | None:
    """The ZIP in a free-text postal address, read the way an
    address is written: a bare 5-digit run is NOT trusted on its
    own (a street number like 21925 is one too) — the ZIP is
    the one after the two-letter state ("Little Falls, MN
    56345"), else the LAST 5-digit run (an address ends with
    its ZIP). None = the address carries no ZIP-shaped tail."""
    text = postal_address or ""
    state_match = _STATE_ZIP.search(text)
    if state_match is not None:
        return state_match.group(1)
    runs = _ZIP_IN_TEXT.findall(text)
    return runs[-1] if runs else None


def near_you(
    db: Session,
    viewer: core_models.User,
    *,
    radius_miles: float,
) -> dict:
    """The widget's read: the nearest findable agents to the
    VIEWER'S OWN ZIP, flattened to one row per (agent, company).

    The viewer's ZIP is the one in the postal address they keep
    on their profile (Settings → Profile → Report contact
    details) — the same fact the warranty router reads — pulled
    by `_viewer_zip` (state-prefixed or trailing run; a bare
    street number is never mistaken for it). No ZIP on file is an honest
    `no_location` (the widget says so and doors to the profile);
    a ZIP the bundled centroid dataset doesn't know is
    `unknown_zip`; agents exist only through the SAME
    search_local_agents the Find an Agent page runs, so the
    findability bar (publicly listed + territory + VERIFIED
    representation) and the distance math (to the nearest point
    of the territory, 0 = covers the ZIP) are identical by
    construction. Company logo fields ride each row so the
    widget paints the directory's own CompanyLogo treatment.
    """
    base: dict = {
        "radius_miles": radius_miles,
        "zip": None,
        "point": None,
        "results": [],
    }
    zip5 = _viewer_zip(viewer.postal_address or "")
    if zip5 is None:
        return {**base, "state": "no_location"}
    if zip_centroid(zip5) is None:
        return {**base, "state": "unknown_zip", "zip": zip5}
    found = search_local_agents(
        db, viewer.id, zip_code=zip5, radius_miles=radius_miles
    )
    if found is None:  # pragma: no cover - centroid check above rules it out
        return {**base, "state": "unknown_zip", "zip": zip5}
    # The viewer's own logos for these dealers (personal
    # edits): company_name above already speaks the viewer's
    # layer, so the logo rides the same effective key — a
    # viewer who replaced a dealer's logo sees HIS logo
    # (and its rendition), not the directory's.
    logo_keys = service.personal_logo_map(
        db,
        viewer.id,
        [
            company_ref["company_id"]
            for card in found["results"]
            for company_ref in card["companies"]
        ],
    )
    results = []
    for card in found["results"]:
        companies = []
        for company_ref in card["companies"]:
            try:
                company_id = uuid.UUID(str(company_ref["company_id"]))
            except (ValueError, TypeError):
                continue
            company = db.get(models.DealerCompany, company_id)
            if company is None:
                continue
            companies.append(
                {
                    "company_id": str(company.id),
                    "company_name": company_ref["company_name"],
                    "logo_url": service.logo_url_for(
                        logo_keys.get(company.id, company.logo_key)
                    ),
                    "logo_tile": company.logo_tile,
                    "connected": company_ref["connected"],
                    "is_preferred": company_ref["is_preferred"],
                }
            )
        if not companies:
            continue
        results.append(
            {
                "agent_user_id": card["agent_user_id"],
                "display_name": card["display_name"],
                "service_area": card["service_area"],
                "photo_url": card.get("photo_url"),
                "distance_miles": card["distance_miles"],
                "covers_zip": card["covers_zip"],
                "companies": companies,
            }
        )
    return {
        **base,
        "state": "ok" if results else "none_near",
        "zip": found["zip"],
        "point": found["point"],
        "results": results,
    }
