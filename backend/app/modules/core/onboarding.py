"""Onboarding wizard system (owner design 2026-10-31, built
2026-11-07).

Signup is just an account (email + login). Everything else — the
account's group set, the signup basics, modules, settings,
sharing — is set up afterwards in ONE guided pass: the wizard.
This service is the pass's memory and plan; it stores NO settings.
Every wizard step writes through the same machinery the Settings
page uses (POST /core/account-type, PATCH /core/me, the per-user
module switches, the settings sections' own saves) — this module
only records where the account stands (onboarding_progress) and
computes what remains.

THE PLAN IS REGISTRY-DRIVEN, never a hard-coded script:

- "account_type" and "basics" are probe steps: done exactly when
  the account itself says so (a non-empty group set; a country on
  file) — the same signals the legacy completion gate reads, so
  the wizard and Settings can never disagree about them.
- "module:<id>" steps come straight from the module control
  registry read (module_control.user_module_prefs): every feature
  module the account's groups entitle, on the same switchboard
  state everything else reads — a parked module is absent while
  parked and appears when it returns, with no code change here.
- "setting:<section-id>" steps are the frontend settings
  registry's own sections (that registry lives in the client);
  this service carries their progress rows opaquely.

FLOWS. An account born after the wizard shipped carries a
"__fresh__" row (written by the ONE creation path) and is in the
WIZARD flow: the app gate lets it in, Home carries the setup
banner, and the wizard walks its steps. An account that predates
the wizard never gets that row: one missing its bare bones stays
on the legacy one-time completion gate, exactly as before; a
COMPLETE pre-existing account is in the EXISTING flow — no wizard
is ever forced on it, but the living part still reaches it (below).

THE LIVING PART. Each account has a BASELINE: the feature-module
ids it was entitled to when the baseline was taken (first plan
read for an existing account; when a fresh account finishes or
dismisses its first pass). A module that becomes entitled later —
a new feature shipping, a parked module returning, an operator
lighting a tier — is absent from the baseline and unresolved, so
it surfaces as a NEW step: one inbox notification ("a new feature
is available — do you want to set it up?") and a banner, until the
account resolves it (done or skipped). Resolved steps never
re-prompt; an ignored one stays quietly listed in the setup hub.

Dismissal ("__dismissed__") waives the prompts, never the setup:
the banner stands down until a step is notified AFTER the waiver,
and the hub stays reopenable from Settings at any time.
"""

import json
import re
import uuid

from sqlalchemy.orm import Session

from app.modules.core import inbox, models, module_control, tiers

FRESH_KEY = "__fresh__"
BASELINE_KEY = "__baseline__"
DISMISSED_KEY = "__dismissed__"

STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_NOTIFIED = "notified"
STATUSES = frozenset({STATUS_DONE, STATUS_SKIPPED, STATUS_NOTIFIED})

ACCOUNT_TYPE_STEP = "account_type"
BASICS_STEP = "basics"
MODULE_STEP_PREFIX = "module:"
SETTING_STEP_PREFIX = "setting:"

_STEP_KEY_RE = re.compile(r"^(account_type|basics|(module|setting):[a-z0-9_:-]+)$")


# -- row helpers ---------------------------------------------------


def _rows(db: Session, user_id: uuid.UUID) -> dict[str, models.OnboardingProgress]:
    return {
        row.step_key: row
        for row in db.query(models.OnboardingProgress)
        .filter(models.OnboardingProgress.user_id == user_id)
        .all()
    }


def _upsert(
    db: Session,
    user_id: uuid.UUID,
    step_key: str,
    status: str,
    detail: str | None = None,
) -> models.OnboardingProgress:
    row = (
        db.query(models.OnboardingProgress)
        .filter(
            models.OnboardingProgress.user_id == user_id,
            models.OnboardingProgress.step_key == step_key,
        )
        .one_or_none()
    )
    if row is None:
        row = models.OnboardingProgress(
            user_id=user_id, step_key=step_key, status=status, detail=detail or ""
        )
        db.add(row)
    else:
        row.status = status
        if detail is not None:
            row.detail = detail
    db.commit()
    db.refresh(row)
    return row


def mark_fresh(db: Session, user: models.User) -> None:
    """The birth marker: every account created through the ONE
    creation path (service._create_user — password signup and
    social login alike) starts in the wizard flow. Idempotent;
    called with its own commit so the marker survives even if a
    later creation step is retried."""
    if (
        db.query(models.OnboardingProgress)
        .filter(
            models.OnboardingProgress.user_id == user.id,
            models.OnboardingProgress.step_key == FRESH_KEY,
        )
        .one_or_none()
        is None
    ):
        _upsert(db, user.id, FRESH_KEY, STATUS_DONE)


def _baseline_modules(row: models.OnboardingProgress | None) -> list[str] | None:
    if row is None:
        return None
    try:
        value = json.loads(row.detail or "[]")
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _entitled_module_ids(db: Session, user: models.User) -> list[str]:
    """The wizard's module universe: the module-control registry
    read for THIS account (operator layer only — the user's own
    switches don't remove a module from setup, they ARE its
    setup). Registry order (nav order) is preserved."""
    return [pref["id"] for pref in module_control.user_module_prefs(db, user)]


# -- the plan --------------------------------------------------------


def get_plan(db: Session, user: models.User) -> dict:
    """The account's setup plan: flow, waiver state, the server
    steps (probes + registry module steps), every progress row
    (the client merges its settings-registry steps over them),
    and the new-feature modules this read surfaced.

    Reading the plan is also how the living part breathes:
    baselines are taken and new-feature notifications are minted
    here, each exactly once (the progress row is the dedupe)."""
    rows = _rows(db, user.id)
    fresh = FRESH_KEY in rows
    complete = bool(user.account_types) and bool(user.country)
    entitled = _entitled_module_ids(db, user)

    if fresh:
        flow = "wizard"
    elif complete:
        flow = "existing"
    else:
        flow = "legacy"

    baseline = _baseline_modules(rows.get(BASELINE_KEY))
    if flow == "existing" and baseline is None:
        # A pre-existing, fully-set-up account: its baseline is
        # the world as it already knows it. Nothing it has today
        # ever prompts; only what arrives later does.
        _upsert(db, user.id, BASELINE_KEY, STATUS_DONE, json.dumps(entitled))
        baseline = list(entitled)
        rows = _rows(db, user.id)

    steps: list[dict] = [
        {
            "key": ACCOUNT_TYPE_STEP,
            "kind": "account_type",
            "status": STATUS_DONE if user.account_types else "pending",
        },
        {
            "key": BASICS_STEP,
            "kind": "basics",
            "status": STATUS_DONE if user.country else "pending",
        },
    ]

    new_feature_modules: list[str] = []
    if flow == "wizard" and baseline is None:
        # First pass: every entitled module is a setup step (a
        # fresh account has no groups yet, so before step 1 this
        # list is empty and fills in as the pass proceeds — the
        # branching the design calls for).
        for module_id in entitled:
            row = rows.get(MODULE_STEP_PREFIX + module_id)
            steps.append(
                {
                    "key": MODULE_STEP_PREFIX + module_id,
                    "kind": "module",
                    "module_id": module_id,
                    "status": row.status if row else "pending",
                }
            )
        # The baseline is taken once the first pass is settled —
        # dismissed, or every module step resolved — so modules
        # arriving afterwards read as NEW against it.
        module_rows = [
            rows.get(MODULE_STEP_PREFIX + m) for m in entitled
        ]
        settled = DISMISSED_KEY in rows or (
            bool(entitled)
            and all(r is not None and r.status in (STATUS_DONE, STATUS_SKIPPED) for r in module_rows)
        )
        if settled and complete:
            _upsert(db, user.id, BASELINE_KEY, STATUS_DONE, json.dumps(entitled))
            baseline = list(entitled)
            rows = _rows(db, user.id)
    elif baseline is not None:
        # Settled accounts (existing flow, or a fresh account past
        # its first pass): the baseline modules stay LISTED with
        # their recorded state — the setup hub's progress panel
        # shows the whole pass, not just what's new — and a
        # module the baseline doesn't know and no row resolves
        # is a new feature for this account.
        for module_id in entitled:
            if module_id not in baseline:
                continue
            row = rows.get(MODULE_STEP_PREFIX + module_id)
            steps.append(
                {
                    "key": MODULE_STEP_PREFIX + module_id,
                    "kind": "module",
                    "module_id": module_id,
                    "status": row.status if row else "pending",
                    "new": False,
                }
            )
        for module_id in entitled:
            if module_id in baseline:
                continue
            key = MODULE_STEP_PREFIX + module_id
            row = rows.get(key)
            if row is not None and row.status in (STATUS_DONE, STATUS_SKIPPED):
                continue
            if row is None:
                row = _upsert(db, user.id, key, STATUS_NOTIFIED)
                inbox.create_notification(
                    db,
                    user.id,
                    kind=inbox.KIND_ONBOARDING_NEW_FEATURE,
                    title="A new feature is available",
                    body=(
                        "A new feature just landed in your vault. "
                        "Open Account setup to see it, turn it on, "
                        "and walk through its options."
                    ),
                    data={"module": module_id},
                )
                rows = _rows(db, user.id)
            new_feature_modules.append(module_id)
            steps.append(
                {
                    "key": key,
                    "kind": "module",
                    "module_id": module_id,
                    "status": STATUS_NOTIFIED,
                    "new": True,
                }
            )

    dismissed_row = rows.get(DISMISSED_KEY)
    # The waiver stands until a step is notified after it: a
    # genuinely new arrival re-opens the banner, per the design's
    # "waive the notifications" (not "never hear again").
    dismissed = False
    if dismissed_row is not None:
        dismissed = not any(
            (rows.get(MODULE_STEP_PREFIX + m) is not None)
            and rows[MODULE_STEP_PREFIX + m].updated_at > dismissed_row.updated_at
            for m in new_feature_modules
        )

    resolved = sum(
        1 for s in steps if s["status"] in (STATUS_DONE, STATUS_SKIPPED)
    )
    return {
        "flow": flow,
        "dismissed": dismissed,
        "steps": steps,
        "progress": {
            key: row.status
            for key, row in rows.items()
            if not key.startswith("__")
        },
        "new_feature_modules": new_feature_modules,
        "resolved": resolved,
        "total": len(steps),
    }


# -- writes ----------------------------------------------------------


def set_progress(
    db: Session, user: models.User, step_key: str, status: str
) -> dict:
    """Record one step's outcome (done | skipped). Module steps
    validate against the live feature registry; settings steps
    are the client registry's own keys, carried opaquely under a
    strict key shape. Probe steps (account_type, basics) accept a
    record too — the plan's probe always outranks it — so a client
    can report uniformly.

    The settings-walk and module steps cannot be recorded before
    the account-type pick (owner ruling 2026-11-07): their
    contents are filtered by the account's groups — the walk's
    sections gate on them and module entitlement is read off
    them — so completing one ahead of the pick would record a
    pass over a list that was never the account's to see. The
    wizard routes a typeless account back to the type step; this
    is the same refusal at the API, which is the real gate.

    The one exception is a group-waived rung (tiers.py): its
    accounts hold no types BY DESIGN and their step contents are
    filtered by reach (tier cells), never by groups — there is
    no pick to wait for, so the refusal does not bind them."""
    if status not in (STATUS_DONE, STATUS_SKIPPED):
        raise ValueError("status must be done or skipped")
    if not _STEP_KEY_RE.match(step_key):
        raise ValueError("unknown step key")
    if step_key.startswith(MODULE_STEP_PREFIX):
        module_id = step_key[len(MODULE_STEP_PREFIX) :]
        from app.modules.registry import FEATURE_MODULES

        if module_id not in FEATURE_MODULES:
            raise ValueError("unknown module step")
    if (
        step_key.startswith((MODULE_STEP_PREFIX, SETTING_STEP_PREFIX))
        and not user.account_types
        and not tiers.group_layer_waived(tiers.resolved_tier(user))
    ):
        raise ValueError(
            "Pick your account type first — it decides which "
            "settings and modules are yours."
        )
    _upsert(db, user.id, step_key, status)
    return get_plan(db, user)


def dismiss(db: Session, user: models.User) -> dict:
    """Waive setup prompts (the design's dismiss): the banner
    stands down; nothing is locked and nothing is marked done —
    the steps remain in the hub exactly as they stood."""
    _upsert(db, user.id, DISMISSED_KEY, STATUS_DONE)
    return get_plan(db, user)


def reopen(db: Session, user: models.User) -> dict:
    """Undo a waiver (Settings → Account setup → Resume setup, or
    opening the hub with intent): the banner may speak again."""
    row = (
        db.query(models.OnboardingProgress)
        .filter(
            models.OnboardingProgress.user_id == user.id,
            models.OnboardingProgress.step_key == DISMISSED_KEY,
        )
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return get_plan(db, user)


def sweep_user(db: Session, user_id: uuid.UUID) -> None:
    """Account deletion cascade (the 0038 pattern): the account's
    onboarding rows go with the account. Caller commits."""
    db.query(models.OnboardingProgress).filter(
        models.OnboardingProgress.user_id == user_id
    ).delete(synchronize_session=False)
