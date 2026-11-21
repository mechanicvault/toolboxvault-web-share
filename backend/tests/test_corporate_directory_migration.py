"""Migration 0025 (corporate directory).

Runs the migration's real upgrade()/downgrade() against a
hand-built PRE-0025 database holding the 4 directory companies
0016 seeded, and pins the seed integrity rules:

- exactly 23 directory rows; Titan (unverified) absent;
- general ship-to == exactly Matco / Mac / SUNEX / Astro;
- scoped ship-to == exactly Lisle / GEARWRENCH / DEWALT, each
  WITH its scope note;
- gated brands carry a gate and NO ship-to address;
- HQ/contact addresses never leak into ship_to_*;
- Amazon seeds as a retailer with its returns block;
- the 4 pre-existing companies keep their identity fields;
- the seed is idempotent; downgrade drops the columns.
"""

import importlib.util
import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0025_corporate_directory.py"
)

GENERAL = {"Matco Tools", "Mac Tools", "SUNEX Tools Inc.", "Astro Pneumatic Tool Company"}
SCOPED = {"Lisle Corporation", "GEARWRENCH (Apex Tool Group)", "DEWALT"}
RETAILERS = {"Harbor Freight Tools", "Kobalt", "Husky", "Amazon.com"}
LOGO_TILES = {"Harbor Freight Tools", "Kobalt", "Husky", "PROTO Industrial Tools", "Amazon.com"}
DARK_TILES = {"Mac Tools", "Astro Pneumatic Tool Company"}

# The 0016 seed, verbatim identity fields.
_EXISTING = [
    (
        "Snap-on Incorporated", "", "https://www.snapon.com",
        "2801 80th Street, Kenosha, Wisconsin 53143",
        [
            {"label": "Corporate Office", "number": "877-762-7664"},
            {"label": "Diagnostics Support", "number": "1-800-424-7226"},
        ],
    ),
    (
        "Matco Tools", "customerservice@matcotools.com",
        "https://www.matcotools.com", "4403 Allen Road, Stow, OH 44224",
        [{"label": "Customer Service", "number": "866-289-8665"}],
    ),
    (
        "Mac Tools", "MTCS@sbdinc.com", "https://www.mactools.com",
        "5195 Blazer Parkway, Dublin, OH 43017",
        [{"label": "Customer Service", "number": "1-800-622-8665"}],
    ),
    (
        "Cornwell Quality Tools", "custserv@cornwelltools.com",
        "https://www.cornwelltools.com", "667 Seville Road, Wadsworth, OH 44281",
        [{"label": "General", "number": "1-800-321-8356"}],
    ),
]


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0025_corporate_directory", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0025_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE dealer_companies ("
                " id VARCHAR(36) PRIMARY KEY,"
                " owner_id VARCHAR(36),"
                " name VARCHAR(300) NOT NULL,"
                " email VARCHAR(320) NOT NULL DEFAULT '',"
                " website VARCHAR(500) NOT NULL DEFAULT '',"
                " address TEXT NOT NULL DEFAULT '',"
                " phones JSON NOT NULL DEFAULT '[]',"
                " notes TEXT NOT NULL DEFAULT '',"
                " is_directory BOOLEAN NOT NULL DEFAULT 0,"
                " created_at DATETIME,"
                " updated_at DATETIME"
                ")"
            )
        )
        for name, email, website, address, phones in _EXISTING:
            conn.execute(
                sa.text(
                    "INSERT INTO dealer_companies"
                    " (id, owner_id, name, email, website, address, phones,"
                    "  notes, is_directory)"
                    " VALUES (:i, NULL, :n, :e, :w, :a, :p, 'seed notes', 1)"
                ),
                {
                    "i": str(uuid.uuid4()), "n": name, "e": email,
                    "w": website, "a": address, "p": json.dumps(phones),
                },
            )
    return engine


def _run(conn, fn) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def _rows(conn):
    result = conn.execute(
        sa.text(
            "SELECT name, kind, email, website, address, phones,"
            " warranty_url, warranty_phone, ship_to_name, ship_to_address,"
            " ship_to_scope, ship_to_scope_note, warranty_process,"
            " logo_key, logo_tile, is_directory"
            " FROM dealer_companies"
        )
    )
    out = {}
    for row in result:
        d = dict(row._mapping)
        d["phones"] = json.loads(d["phones"]) if isinstance(d["phones"], str) else d["phones"]
        wp = d["warranty_process"]
        d["warranty_process"] = json.loads(wp) if isinstance(wp, str) else wp
        out[d["name"]] = d
    return out


def test_0025_upgrade_seeds_the_verified_directory():
    migration = _load_migration()
    assert migration.revision == "0025_corporate_directory"
    assert migration.down_revision == "0024_claim_number_unique"
    engine = _pre_0025_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        rows = _rows(conn)

    assert len(rows) == 23
    assert all(r["is_directory"] for r in rows.values())
    assert not any("Titan" in name for name in rows)

    general = {n for n, r in rows.items() if r["ship_to_scope"] == "general"}
    scoped = {n for n, r in rows.items() if r["ship_to_scope"] == "scoped"}
    assert general == GENERAL
    assert scoped == SCOPED
    for name in SCOPED:
        assert rows[name]["ship_to_address"]
        assert rows[name]["ship_to_scope_note"]  # scope never renders bare
    for name in GENERAL:
        assert rows[name]["ship_to_address"]
        assert rows[name]["ship_to_name"]

    gated = set(rows) - GENERAL - SCOPED
    assert len(gated) == 16
    for name in gated:
        assert rows[name]["ship_to_address"] is None, name
        assert rows[name]["ship_to_name"] is None, name
        assert rows[name]["warranty_process"]["gate"], name

    # HQ/contact addresses stay OUT of ship-to (the notes' trap #1).
    assert rows["Snap-on Incorporated"]["ship_to_address"] is None
    assert "RGA" in rows["Snap-on Incorporated"]["warranty_process"]["gate"]
    assert rows["Cornwell Quality Tools"]["ship_to_address"] is None
    assert "custserv@cornwelltools.com" in (
        rows["Cornwell Quality Tools"]["warranty_process"]["gate"]
    )

    # Kinds: exactly the 4 retailers.
    assert {n for n, r in rows.items() if r["kind"] == "retailer"} == RETAILERS
    amazon = rows["Amazon.com"]
    assert amazon["warranty_process"]["gate"]  # per-order returns flow
    assert any(
        "warranty service belongs to the tool's manufacturer" in note
        for note in amazon["warranty_process"]["notes"]
    )
    assert amazon["phones"] == []  # no published CS phone — stays empty

    # Two-number brands: the distinct warranty line is warranty_phone.
    assert rows["Harbor Freight Tools"]["warranty_phone"] == "1-888-838-3421"
    assert rows["SUNEX Tools Inc."]["warranty_phone"] == "877.786.3939"
    sunex_labels = {p["label"] for p in rows["SUNEX Tools Inc."]["phones"]}
    assert {"Customer Service", "Warranty Service"} <= sunex_labels

    # Logos: 18 harvested keys, 5 text tiles, dark tile only Mac/Astro.
    assert {n for n, r in rows.items() if r["logo_key"] is None} == LOGO_TILES
    for name, r in rows.items():
        if r["logo_key"]:
            assert r["logo_key"].startswith("platform/logos/"), name
    assert {n for n, r in rows.items() if r["logo_tile"] == "dark"} == DARK_TILES

    # OEMTOOLS publishes no phone anywhere — phones stay empty.
    assert rows["OEMTOOLS (GreatNeck Tools LLC)"]["phones"] == []


def test_0025_preserves_the_existing_four_companies_identity():
    migration = _load_migration()
    engine = _pre_0025_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        rows = _rows(conn)
    for name, email, website, address, phones in _EXISTING:
        row = rows[name]
        assert row["email"] == email
        assert row["website"] == website
        assert row["address"] == address
        seeded_numbers = {p["number"] for p in phones}
        kept_numbers = {p["number"] for p in row["phones"]}
        assert seeded_numbers <= kept_numbers, name
    # The CS guarantee must not duplicate a line the company already
    # lists in another format: Matco's dataset number carries the
    # "(866-BUY-TOOL)" vanity suffix, Snap-on's a leading 1 — both
    # are the same lines the 0016 seed already published.
    assert len(rows["Matco Tools"]["phones"]) == 1
    assert len(rows["Snap-on Incorporated"]["phones"]) == 2
    assert len(rows["Mac Tools"]["phones"]) == 1
    assert len(rows["Cornwell Quality Tools"]["phones"]) == 1


def test_0025_seed_is_idempotent():
    migration = _load_migration()
    engine = _pre_0025_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, lambda: migration.seed_corporate_directory(conn))
        _run(conn, lambda: migration.seed_corporate_directory(conn))
        rows = _rows(conn)
    assert len(rows) == 23


def test_0025_downgrade_drops_the_corporate_columns():
    migration = _load_migration()
    engine = _pre_0025_engine()
    with engine.begin() as conn:
        _run(conn, migration.upgrade)
        _run(conn, migration.downgrade)
        columns = {
            c["name"] for c in sa.inspect(conn).get_columns("dealer_companies")
        }
    assert not {
        "kind", "warranty_url", "warranty_phone", "ship_to_name",
        "ship_to_address", "ship_to_scope", "ship_to_scope_note",
        "warranty_process", "logo_key", "logo_tile",
    } & columns
    assert {"name", "email", "website", "address", "phones"} <= columns
