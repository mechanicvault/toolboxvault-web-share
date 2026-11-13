"""The report TYPE catalog (Reports page redesign, 2026-11-06).

One registry of every report kind the redesigned page can make.
A type is a promise the system can keep: a builder that exists
today, the settings that builder honestly takes, the formats a
real producer exists for, and a HOME AREA (quick | accounting —
Ryan's split: Quick is the day-to-day working set; Accounting is
what's geared to taxes and accountants). The wizard, the saved
templates and the History all speak in these keys, and deleting
a saved template never touches the catalog: every kind stays
reachable from the wizard forever.

Name and description composers live here too: a saved template's
name and its system-written description are composed from the
type + settings in the OWNER's locale (the description is stored
on the template — composed once, at save/seed time, and editable
by the user from there).

Two honesty notes the catalog encodes:

- tax_179 IS the Section 179 worksheet. The older tax_year
  builder (activity.build_tax_year) already IS that document —
  its title is "Tax / Section 179 worksheet", purchases split by
  the business-use flag, placed-in-service dates — so the
  catalog carries ONE type for it, not two names for one file.
- "Fiscal year" settings ride the calendar year. No fiscal-
  calendar offset exists anywhere in the system (every year
  report has always taken a calendar year); the year a fiscal
  template asks for at run time is that calendar year.
"""

from app.core.i18n import resolve_locale

# settings kinds:
#   none        — the type takes no settings
#   year        — one calendar year (chosen in the wizard;
#                 asked again at run time for saved templates)
#   year_or_all — a year, or all time (repair costs)
#   period      — an optional date range (start / end)
#   inventory   — format + grouping + sets mode over the fixed
#                 full-inventory column spec
TYPES: dict[str, dict] = {
    "inventory": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "inventory",
        # The inventory dataset rides the reports module itself.
        "module": None,
    },
    "open_claims": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": "claims",
    },
    "open_truck_accounts": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": "truck_accounts",
    },
    "checked_out": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": "borrowing",
    },
    "lost_stolen": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "period",
        "module": None,
    },
    "warranty_claims": {
        "home": "quick",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "period",
        "module": "dealers",
    },
    "year_end": {
        "home": "accounting",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "year",
        "module": None,
    },
    "repair_costs": {
        "home": "accounting",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "year_or_all",
        # The dedicated /repair-costs routes gate on maintenance
        # (the repair books' home) — the catalog mirrors them.
        "module": "maintenance",
    },
    "sales": {
        "home": "accounting",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "period",
        "module": None,
    },
    "tax_179": {
        "home": "accounting",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "year",
        "module": None,
    },
}

AREAS = ("quick", "accounting", "admin")

# Admin Reports (admin lane, owner 2026-11-06): the SAME
# catalog/templates/generation machinery, an admin audience.
# These types live apart from TYPES on purpose: the user-facing
# catalog builder iterates TYPES, so admin datasets can never
# leak into a member's catalog, wizard or saved lists. The
# routes additionally gate every admin type to god +
# moderator_admin seats server-side. "home" is "admin" so the
# wizard's grouping and the template area agree.
ADMIN_TYPES: dict[str, dict] = {
    "admin_site_stats": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": None,
    },
    "admin_users": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": None,
    },
    "admin_inventory": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": None,
    },
    "admin_payments": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "none",
        "module": None,
    },
    "admin_revenue_year": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "year",
        "module": None,
    },
    "admin_revenue_quarter": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "year",
        "module": None,
    },
    "admin_accounting": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "period",
        "module": None,
    },
    "admin_ai_usage": {
        "home": "admin",
        "formats": ("pdf", "csv", "xlsx"),
        "settings": "period",
        "module": None,
    },
}


def type_view(key: str, *, available: bool, owner=None) -> dict:
    spec = TYPES.get(key) or ADMIN_TYPES[key]
    view = {
        "key": key,
        "home_area": spec["home"],
        "formats": list(spec["formats"]),
        "settings": spec["settings"],
        "module": spec["module"],
        "available": available,
    }
    if owner is not None:
        # The wizard's type picker shows the same system-written
        # name + plain-language description the templates carry.
        view["name"] = default_name(key, {}, owner)
        view["description"] = default_description(key, {}, owner)
    return view


# -- names + system descriptions, per locale ----------------------

_TEXT = {
    "en": {
        "inventory": (
            "Full inventory report",
            "Every tool, battery and set you own: names, model and "
            "serial numbers, quantities, prices, categories and totals.",
        ),
        "open_claims": (
            "Open repair claims",
            "Every repair claim still open, with its status, the "
            "item, the dealer or agent it runs through, and the "
            "amount claimed.",
        ),
        "open_truck_accounts": (
            "Open truck accounts",
            "The full ledger of every open truck account — every "
            "charge and payment, with the running balance on each "
            "account. Closed accounts aren't included.",
        ),
        "checked_out": (
            "Checked out items",
            "Everything currently checked out — what you lent out "
            "and what you're holding — with due dates.",
        ),
        "lost_stolen": (
            "Lost / stolen",
            "Your lost and stolen reports, valued at purchase "
            "cost where it's recorded.",
        ),
        "warranty_claims": (
            "Warranty claims",
            "Warranty service requests you sent to dealers, with "
            "the linked repair costs where recorded.",
        ),
        "year_end": (
            "Fiscal year-end spending",
            "Everything you spent on tools in the year, plus "
            "sales, losses and repair spend — the year-end report "
            "for your records, the one to give your tax preparer.",
        ),
        "year_end_year": (
            "Fiscal year-end spending — {year}",
            "Everything you spent on tools in {year}, plus sales, "
            "losses and repair spend — the year-end report for "
            "your records, the one to give your tax preparer.",
        ),
        "repair_costs": (
            "Fiscal year repair claim costs",
            "What repairs cost you, for the fiscal year you pick "
            "when you run it.",
        ),
        "repair_costs_year": (
            "Fiscal year repair claim costs — {year}",
            "What repairs cost you in {year}: every repair claim "
            "with a recorded cost.",
        ),
        "repair_costs_all": (
            "Repair claim costs — all time",
            "What repairs cost you, all time: every repair claim "
            "with a recorded cost.",
        ),
        "sales": (
            "Sales",
            "Everything you sold, from your sold ledger — "
            "reversals subtract.",
        ),
        "tax_179": (
            "Tax 179 worksheet",
            "Tools and equipment placed in service in the year, "
            "split by business use — the Section 179 worksheet "
            "for your tax preparer. Not tax advice.",
        ),
        "tax_179_year": (
            "Tax 179 worksheet — {year}",
            "Tools and equipment placed in service in {year}, "
            "split by business use — the Section 179 worksheet "
            "for your tax preparer. Not tax advice.",
        ),
        "admin_site_stats": (
            "Site overview",
            "The whole site at a glance: members by tier and by "
            "type, free and paying accounts (paying split by "
            "plan and billing period), tools logged, and monthly "
            "recurring revenue.",
        ),
        "admin_users": (
            "User directory",
            "Every member account: name, account number, email, "
            "tier, sign-up date, and how many tools they hold.",
        ),
        "admin_inventory": (
            "Inventory across the site",
            "What the whole membership holds: per-member item "
            "counts and inventory values, with site totals.",
        ),
        "admin_payments": (
            "Payment accounts",
            "Every member's plan and subscription state — who "
            "pays, who is free, and what each plan is worth.",
        ),
        "admin_revenue_year": (
            "Revenue by month",
            "New paying accounts and monthly recurring revenue "
            "for each month of the year you pick.",
        ),
        "admin_revenue_year_year": (
            "Revenue by month — {year}",
            "New paying accounts and monthly recurring revenue "
            "for each month of {year}.",
        ),
        "admin_revenue_quarter": (
            "Revenue by quarter",
            "New paying accounts and monthly recurring revenue "
            "for each quarter of the year you pick.",
        ),
        "admin_revenue_quarter_year": (
            "Revenue by quarter — {year}",
            "New paying accounts and monthly recurring revenue "
            "for each quarter of {year}.",
        ),
        "admin_accounting": (
            "Accounting",
            "The go-to payment report for any date range: "
            "revenue and accounts by plan, free vs paying, "
            "subscription states, new paying accounts and "
            "cancellations in the period, and monthly "
            "recurring revenue.",
        ),
        "admin_ai_usage": (
            "AI usage",
            "Who used the AI, when, for what, and how many "
            "tokens and wallet credits it took — site totals "
            "first, then one section per account, for any date "
            "range.",
        ),
    },
    "es": {
        "inventory": (
            "Informe completo de inventario",
            "Cada herramienta, batería y juego que posee: nombres, "
            "números de modelo y de serie, cantidades, precios, "
            "categorías y totales.",
        ),
        "open_claims": (
            "Reclamos de reparación abiertos",
            "Cada reclamo de reparación aún abierto, con su estado, "
            "el artículo, el distribuidor o agente que lo tramita y "
            "el importe reclamado.",
        ),
        "open_truck_accounts": (
            "Cuentas de camión abiertas",
            "El libro completo de cada cuenta de camión abierta — "
            "cada cargo y pago, con el saldo actualizado de cada "
            "cuenta. Las cuentas cerradas no se incluyen.",
        ),
        "checked_out": (
            "Artículos prestados",
            "Todo lo que está prestado ahora — lo que usted prestó "
            "y lo que tiene en su poder — con fechas de devolución.",
        ),
        "lost_stolen": (
            "Perdidos / robados",
            "Sus reportes de pérdida y robo, valorados al costo de "
            "compra donde esté registrado.",
        ),
        "warranty_claims": (
            "Reclamos de garantía",
            "Solicitudes de servicio de garantía que envió a los "
            "distribuidores, con los costos de reparación "
            "vinculados donde estén registrados.",
        ),
        "year_end": (
            "Gasto de fin de año fiscal",
            "Todo lo que gastó en herramientas en el año, más "
            "ventas, pérdidas y gasto en reparaciones — el informe "
            "de fin de año para sus registros, el que se entrega a "
            "su preparador de impuestos.",
        ),
        "year_end_year": (
            "Gasto de fin de año fiscal — {year}",
            "Todo lo que gastó en herramientas en {year}, más "
            "ventas, pérdidas y gasto en reparaciones — el informe "
            "de fin de año para sus registros, el que se entrega a "
            "su preparador de impuestos.",
        ),
        "repair_costs": (
            "Costos de reclamos de reparación del año fiscal",
            "Lo que le costaron las reparaciones, para el año "
            "fiscal que elija al ejecutarlo.",
        ),
        "repair_costs_year": (
            "Costos de reclamos de reparación del año fiscal — {year}",
            "Lo que le costaron las reparaciones en {year}: cada "
            "reclamo de reparación con un costo registrado.",
        ),
        "repair_costs_all": (
            "Costos de reclamos de reparación — todo el tiempo",
            "Lo que le costaron las reparaciones, todo el tiempo: "
            "cada reclamo de reparación con un costo registrado.",
        ),
        "sales": (
            "Ventas",
            "Todo lo que vendió, de su registro de ventas — las "
            "anulaciones restan.",
        ),
        "tax_179": (
            "Hoja de trabajo del Impuesto 179",
            "Herramientas y equipo puestos en servicio en el año, "
            "separados por uso comercial — la hoja de trabajo de "
            "la Sección 179 para su preparador de impuestos. No "
            "es asesoría fiscal.",
        ),
        "tax_179_year": (
            "Hoja de trabajo del Impuesto 179 — {year}",
            "Herramientas y equipo puestos en servicio en "
            "{year}, separados por uso comercial — la hoja de "
            "trabajo de la Sección 179 para su preparador de "
            "impuestos. No es asesoría fiscal.",
        ),
        "admin_site_stats": (
            "Resumen del sitio",
            "Todo el sitio de un vistazo: miembros por nivel y "
            "por tipo, cuentas gratuitas y de pago (las de pago "
            "separadas por plan y período de facturación), "
            "herramientas registradas e ingresos recurrentes "
            "mensuales.",
        ),
        "admin_users": (
            "Directorio de usuarios",
            "Cada cuenta de miembro: nombre, número de cuenta, "
            "correo, nivel, fecha de registro y cuántas "
            "herramientas tiene.",
        ),
        "admin_inventory": (
            "Inventario de todo el sitio",
            "Lo que tiene toda la membresía: artículos y valor "
            "de inventario por miembro, con totales del sitio.",
        ),
        "admin_payments": (
            "Cuentas de pago",
            "El plan y el estado de suscripción de cada miembro "
            "— quién paga, quién es gratuito y cuánto vale cada "
            "plan.",
        ),
        "admin_revenue_year": (
            "Ingresos por mes",
            "Cuentas de pago nuevas e ingresos recurrentes "
            "mensuales de cada mes del año que elija.",
        ),
        "admin_revenue_year_year": (
            "Ingresos por mes — {year}",
            "Cuentas de pago nuevas e ingresos recurrentes "
            "mensuales de cada mes de {year}.",
        ),
        "admin_revenue_quarter": (
            "Ingresos por trimestre",
            "Cuentas de pago nuevas e ingresos recurrentes "
            "mensuales de cada trimestre del año que elija.",
        ),
        "admin_revenue_quarter_year": (
            "Ingresos por trimestre — {year}",
            "Cuentas de pago nuevas e ingresos recurrentes "
            "mensuales de cada trimestre de {year}.",
        ),
        "admin_accounting": (
            "Contabilidad",
            "El informe de pagos principal para cualquier rango "
            "de fechas: ingresos y cuentas por plan, gratuitas "
            "frente a de pago, estados de suscripción, cuentas "
            "de pago nuevas y cancelaciones en el período e "
            "ingresos recurrentes mensuales.",
        ),
        "admin_ai_usage": (
            "Uso de IA",
            "Quién usó la IA, cuándo, para qué y cuántos tokens "
            "y créditos de la billetera costó — totales del sitio "
            "primero y luego una sección por cuenta, para "
            "cualquier rango de fechas.",
        ),
    },
}


def _text(owner) -> dict:
    return _TEXT[resolve_locale(owner)]


def default_name(report_type: str, settings: dict, owner) -> str:
    """The name a generated report (or a fresh template) carries
    when nobody typed one: the type's own name, year-stamped
    where the settings pin a year."""
    text = _text(owner)
    year = (settings or {}).get("year")
    if year and f"{report_type}_year" in text:
        return text[f"{report_type}_year"][0].format(year=year)
    if report_type == "repair_costs" and not year:
        return text["repair_costs_all"][0]
    return text[report_type][0]


def default_description(report_type: str, settings: dict, owner) -> str:
    """The system-written description for a type + settings, in
    the owner's locale — plain language, the year named only
    when the settings pin one (a fiscal template's description
    never goes stale: it says the year is picked at run time).

    The saved format is deliberately NOT part of the words
    (sweep fix 05-F6): a saved row offers a run button per
    format (PDF / CSV / XLSX) and runs in whichever one the
    user picks, so a description claiming "Saved as PDF" told
    the wrong story for two of its own three buttons. The
    format buttons themselves carry the formats."""
    text = _text(owner)
    settings = settings or {}
    year = settings.get("year")
    if year and f"{report_type}_year" in text:
        body = text[f"{report_type}_year"][1].format(year=year)
    elif report_type == "repair_costs" and not year:
        body = text["repair_costs_all"][1]
    else:
        body = text[report_type][1]
    return body


# -- the seven seeded defaults (spec, 2026-11-06) ------------------
#
# (report_type, area, settings). Names/descriptions are composed
# at seed time in the user's locale by the functions above, so a
# default is indistinguishable from a template the user saved —
# including being deletable like one.

DEFAULT_TEMPLATES: tuple[tuple[str, str, dict], ...] = (
    ("inventory", "quick", {"format": "pdf", "grouping": "category", "sets_mode": "full"}),
    ("open_claims", "quick", {"format": "pdf"}),
    ("open_truck_accounts", "quick", {"format": "pdf"}),
    ("checked_out", "quick", {"format": "pdf"}),
    ("year_end", "accounting", {"format": "pdf"}),
    ("repair_costs", "accounting", {"format": "pdf"}),
    ("tax_179", "accounting", {"format": "pdf"}),
)
