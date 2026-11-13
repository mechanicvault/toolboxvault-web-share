"""Corporate directory (owner 2026-10-19): warranty-service data
for the platform dealer directory.

dealer_companies gains the corporate fields (kind, warranty URL /
phone, ship-to block with scope, warranty process, logo) and this
migration seeds the 23 brands verified from OFFICIAL brand sources
(see goals/toolbox-vault-website/files/corporate-directory-data.json
and its notes — Titan is deliberately absent: unverified).

Seed discipline (the notes' traps, enforced here):
  - ship_to_* is set ONLY where the brand officially publishes the
    address FOR warranty/repair mail-in (4 general + 3 scoped).
    Scoped rows always carry their scope note.
  - Gated brands (16) carry warranty_process.gate and NO ship-to;
    HQ/contact addresses stay in `address` and never leak into
    ship_to_*.
  - The 4 companies seeded by 0016 keep their identity fields
    (name/email/website/address/notes); only their corporate fields
    are filled in, and their customer-service number is guaranteed
    present in `phones`.
  - logo_key points at platform/logos/<file> for the 18 brands
    whose official logo was harvested; the other 5 render the text
    tile (logo_key NULL) — never a substitute logo.

The seed is idempotent: it upserts directory rows by name
(owner_id NULL), so re-running changes nothing.

Revision ID: 0025_corporate_directory
Revises: 0024_claim_number_unique
Create Date: 2026-10-19
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_corporate_directory"
down_revision: str | None = "0024_claim_number_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The 23 verified brands. `customer_service_phone` is seed-internal:
# for new rows it becomes the phones entry labeled "Customer
# Service"; for the 4 pre-existing rows it only guarantees that
# number is present in their phones.
_SEED = [{'name': 'Amazon.com',
  'kind': 'retailer',
  'website': 'https://www.amazon.com',
  'warranty_url': 'https://www.amazon.com/gp/help/customer/display.html?nodeId=201819200',
  'warranty_phone': None,
  'customer_service_phone': None,
  'phones': [],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No fixed mail-in address is published: returns are started online '
                               'through Your Orders / the Online Returns Center, and Amazon '
                               'provides the return label, drop-off option or address for that '
                               'specific return during the flow.',
                       'notes': ['Amazon does not publish a general customer-service phone number '
                                 'on its official help pages as found; support is reached through '
                                 'the Amazon Customer Service / Your Orders flow, where customers '
                                 "can call or chat with Amazon customer support and use 'Get "
                                 "Product Support' from the Your Orders page for eligible items.",
                                 "Per Amazon's official About Amazon returns article: free, "
                                 'convenient returns are offered on most items delivered in the '
                                 "U.S. (look for the 'FREE Returns' badge), with 10,000+ drop-off "
                                 "locations including Whole Foods Market, Kohl's, Staples, The UPS "
                                 'Store and FedEx Office, and most eligible refunds are issued '
                                 'within five hours of drop-off.',
                                 'Verification caveat: Amazon.com help pages returned HTTP 403 to '
                                 'the research fetcher, so help-page specifics beyond the '
                                 "returns-policy URL (cited on Amazon's own Seller Central) could "
                                 'not be directly re-verified page-by-page in this pass.',
                                 'Amazon handles returns only — warranty service belongs to the '
                                 "tool's manufacturer. Find the brand in this directory."]},
  'logo_key': None,
  'logo_tile': None},
 {'name': 'Astro Pneumatic Tool Company',
  'kind': 'manufacturer',
  'website': 'https://astrotools.com/',
  'warranty_url': 'https://astrotools.com/warranty/',
  'warranty_phone': None,
  'customer_service_phone': '(800) 221-9705',
  'phones': [{'label': 'Customer Service', 'number': '(800) 221-9705'}],
  'ship_to_name': 'ASTRO PNEUMATIC TOOL',
  'ship_to_address': '1230 Santa Anita Ave, Suite E\nSouth El Monte, CA 91733',
  'ship_to_scope': 'general',
  'ship_to_scope_note': None,
  'warranty_process': {'gate': None,
                       'notes': ["Warranty page states 'ALL REPAIRS MUST BE SENT TO' the South El "
                                 "Monte, CA address, which the contact page also labels 'ASTRO "
                                 "HEADQUARTERS & REPAIR CENTER'.",
                                 'One-year limited warranty from date of first use for most '
                                 'products; lifetime warranty applies only to items whose '
                                 'manuals/advertising denote it (e.g., most hardline '
                                 'sockets/ratchets).',
                                 'Returns must include distributor name/address, adequate proof of '
                                 'date of purchase or a copy of the warranty card, and a short '
                                 'note explaining the problem; defective air tools/hydraulics are '
                                 'sent freight prepaid to the CA warehouse and Astro covers return '
                                 'shipping on warranty items only.',
                                 'Lifetime claims can start by emailing customer service with a '
                                 'photo/image of the broken tool, model/part number and shipping '
                                 'name/address; proof of purchase may be requested.']},
  'logo_key': 'platform/logos/astro-pneumatic.png',
  'logo_tile': 'dark'},
 {'name': 'CRAFTSMAN',
  'kind': 'manufacturer',
  'website': 'https://www.craftsman.com',
  'warranty_url': 'https://www.craftsman.com/warranty',
  'warranty_phone': None,
  'customer_service_phone': '888-331-4569',
  'phones': [{'label': 'Customer Service', 'number': '888-331-4569'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No mail-in address is published on the official warranty page — if '
                               'a CRAFTSMAN product requires replacement under warranty, return '
                               'the product to the original place of purchase for replacement, '
                               'depending on the warranty coverage by category.',
                       'notes': ['Return-to-place-of-purchase model: the warranty page directs '
                                 'owners to return the product to the original place of purchase '
                                 'for replacement; it publishes no mail-in/RMA address.',
                                 'Owners can create or log in to a CRAFTSMAN CLUB account to '
                                 'register products and obtain additional warranty information.',
                                 'Customer Service is reachable by chat, the support form at '
                                 'support.craftsman.com, or 888-331-4569 during operational hours, '
                                 'Monday to Sunday, 7 AM to 11 PM ET.',
                                 'Warranty details on the page are organized by category: hand '
                                 'tools & mechanic tools, storage & garage, power tools, and '
                                 'outdoor tools & equipment.']},
  'logo_key': 'platform/logos/craftsman.png',
  'logo_tile': None},
 {'name': 'Capri Tools',
  'kind': 'manufacturer',
  'website': 'https://capritools.com',
  'warranty_url': 'https://capritools.com/warranty-information/',
  'warranty_phone': None,
  'customer_service_phone': '888-723-0550',
  'phones': [{'label': 'Customer Service', 'number': '888-723-0550'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'Start a claim with the online warranty claim form on '
                               'capritools.com/warranty-information/; Capri reviews the claim and '
                               'may ask you to return the product to Capri Tools — no mail-in '
                               'warranty ship-to address is published on the official warranty '
                               'page (the 1788 W 2nd St, Pomona, CA 91766 address on other '
                               'official pages is a general mail/contact address, not a labeled '
                               'warranty ship-to).',
                       'notes': ['Proof of purchase from an authorized retailer is required; '
                                 'warranty applies to the original purchaser in North America '
                                 'only.',
                                 'Support team replies to claims usually within 2 business days; '
                                 'if covered, Capri ships a repair kit, replacement part or '
                                 'replacement tool.',
                                 'Terms vary by product: limited lifetime for '
                                 'ratchets/sockets/wrenches/pliers/screwdrivers, 10 years for '
                                 'rotating vises/hammers/wire strippers, 2 years for pneumatic air '
                                 'tools, 1 year for automotive/torque tools and organizers.',
                                 'Contact page lists phone hours Mon–Fri 7:00 am–4:00 pm Pacific '
                                 'and support@capritools.com for form help.']},
  'logo_key': 'platform/logos/capri-tools.png',
  'logo_tile': None},
 {'name': 'Channellock, Inc.',
  'kind': 'manufacturer',
  'website': 'https://www.channellock.com',
  'warranty_url': 'https://www.channellock.com/warranty/',
  'warranty_phone': None,
  'customer_service_phone': '1-800-724-3018',
  'phones': [{'label': 'Customer Service', 'number': '1-800-724-3018'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'Complete the warranty form on channellock.com/warranty/; eligible '
                               'tools may be exchanged at a participating retailer or shipped back '
                               'to the Channellock plant in Meadville, PA — no full street ship-to '
                               'address is published on the official warranty page (the contact '
                               'page lists only the general company address).',
                       'notes': ['Built Strong Limited Lifetime Warranty covers pliers, wrenches, '
                                 'snips, drivers, pry bars and levels for defects in '
                                 'materials/workmanship to the original owner.',
                                 "Participating retailers (The Home Depot, Lowe's, Do it Best) may "
                                 'process an in-store exchange and may ask for proof of purchase, '
                                 'though Channellock says it is not required by them.',
                                 'Normal wear, misuse, alteration, neglect and heat damage are '
                                 'excluded; Channellock inspects the tool and reserves the right '
                                 'to accept or reject a claim.']},
  'logo_key': 'platform/logos/channellock.png',
  'logo_tile': None},
 {'name': 'Cornwell Quality Tools',
  'kind': 'manufacturer',
  'website': 'https://www.cornwelltools.com',
  'warranty_url': '',
  'warranty_phone': None,
  'customer_service_phone': '1-800-321-8356',
  'phones': [{'label': 'Customer Service', 'number': '1-800-321-8356'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No mail-in warranty ship-to address is published — the official '
                               'Contact Us page routes warranty inquiries by email to '
                               'custserv@cornwelltools.com, and Cornwell products are sold and '
                               'serviced through its mobile tool dealers.',
                       'notes': ['The official Contact Us page publishes email routing only '
                                 '(Warranty Inquiries: custserv@cornwelltools.com; Credit '
                                 'Inquiries and Other Inquiries have separate addresses) and lists '
                                 'the corporate headquarters at 667 Seville Road, Wadsworth, OH '
                                 '44281 — it publishes no phone number and no warranty ship-to '
                                 'address. (HQ address is a contact address, NOT a warranty '
                                 'ship-to — do not present it as one.)',
                                 'Products are sold via mobile tool dealers across the country, '
                                 'per the official History page.',
                                 'The customer service phone above (1-800-321-8356) is published '
                                 "in Cornwell's official product catalog hosted on "
                                 'corporate.cornwelltools.com; no standalone warranty page was '
                                 'found on cornwelltools.com.']},
  'logo_key': 'platform/logos/cornwell.png',
  'logo_tile': None},
 {'name': 'DEWALT',
  'kind': 'manufacturer',
  'website': 'https://www.dewalt.com',
  'warranty_url': 'https://www.dewalt.com/en-us/support/warranty',
  'warranty_phone': None,
  'customer_service_phone': '1-800-433-9258',
  'phones': [{'label': 'Customer Service', 'number': '1-800-433-9258'}],
  'ship_to_name': 'Stanley Black and Decker',
  'ship_to_address': '100 Passmore Lane\nJackson, TN 38305\nAttn: Quality Assurance',
  'ship_to_scope': 'scoped',
  'ship_to_scope_note': 'Hand tools only (Quality Assurance returns). Power tools go to a DeWalt '
                        'service center instead.',
  'warranty_process': {'gate': None,
                       'notes': ['The ship-to address above is published on the warranty page '
                                 "under 'DEWALT Hand Tools Warranty and Returns' (United States) "
                                 'and handles HAND TOOLS only; power tools go to a DEWALT service '
                                 'center or Customer Care.',
                                 'Mechanics tools carry a Full Lifetime Warranty with NO proof of '
                                 "purchase required and 'DO NOT RETURN PRODUCT TO STORE' — contact "
                                 'Customer Care at 1-800-433-9258 (Mon–Sun, 7 AM–11 PM ET) or via '
                                 'the support form and DEWALT will ship a replacement.',
                                 'Most power tools carry a 3-year limited warranty plus a 1-year '
                                 'free service contract and 90-day money-back guarantee; proof of '
                                 'purchase showing when and where the product was purchased may be '
                                 'required.',
                                 'Warranty coverage applies only to products purchased from DEWALT '
                                 'or a DEWALT authorized seller; DEWALT may reject claims for '
                                 'products from unauthorized sellers.']},
  'logo_key': 'platform/logos/dewalt.png',
  'logo_tile': None},
 {'name': 'GEARWRENCH (Apex Tool Group)',
  'kind': 'manufacturer',
  'website': 'https://www.gearwrench.com/',
  'warranty_url': 'https://www.gearwrench.com/warranty',
  'warranty_phone': None,
  'customer_service_phone': '1-877-626-3433',
  'phones': [{'label': 'Customer Service', 'number': '1-877-626-3433'}],
  'ship_to_name': 'Angle Repair & Calibration Service, Inc.',
  'ship_to_address': '175 Angle Drive\nBeckley, WV 25801 USA',
  'ship_to_scope': 'scoped',
  'ship_to_scope_note': 'Torque products only. Hand tools use the EZ Warranty photo claim instead '
                        '— no return needed.',
  'warranty_process': {'gate': None,
                       'notes': ['EZ Warranty for hand tools: if a tool breaks, send a photo of '
                                 'the damage — no need to return the tool itself; claims via the '
                                 'online Warranty Replacement Form, Customer Service at '
                                 '877-626-3433, or warrantysupport@apextoolgroup.com.',
                                 'The ship-to address above is published on the warranty page for '
                                 'Torque Products only (US Torque Wrench Authorized Service '
                                 'Center); torque products must be sent to an Authorized Repair '
                                 'Center for evaluation and the consumer pays shipping to the '
                                 'center.',
                                 'Proof of purchase: GEARWRENCH asks where the tool was bought '
                                 'and, for select purchases such as online retailers, may request '
                                 'proof of purchase to verify eligibility.',
                                 'Warranty periods published on the page: Mechanics Hand Tools — '
                                 'lifetime of the original end-user purchaser; Torque Products — 1 '
                                 'year (plus 90-day calibration guarantee); Diagnostics — 2 years; '
                                 'Tool Storage — 3 years; Tool Cart — 5 years.']},
  'logo_key': 'platform/logos/gearwrench-gw.png',
  'logo_tile': None},
 {'name': 'Harbor Freight Tools',
  'kind': 'retailer',
  'website': 'https://www.harborfreight.com',
  'warranty_url': '',
  'warranty_phone': '1-888-838-3421',
  'customer_service_phone': '1-800-444-3353',
  'phones': [{'label': 'Customer Service', 'number': '1-800-444-3353'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No general mail-in warranty ship-to address is published — returns '
                               'and exchanges are handled at any Harbor Freight store, and certain '
                               'product categories (e.g., pumps, sprayers, and drain cleaners) use '
                               'official Warranty and ESP Claim Forms instead of mail-in returns, '
                               'with opened restricted items not returnable by mail for safety '
                               'reasons.',
                       'notes': ['Proof of purchase is required for all returns and exchanges, and '
                                 'merchandise may be returned within 90 days of purchase for a '
                                 'refund or exchange, per the official Terms and Conditions; a '
                                 'valid government-issued photo ID must be presented at the time '
                                 'of return.',
                                 'The warranty_phone above (1-888-838-3421) is the Extended '
                                 'Service Protection (ESP) and technical support line, published '
                                 'as available 24 hours a day, 7 days a week; ESP plans run 1 and '
                                 "2 years, begin when the manufacturer's warranty ends, and offer "
                                 'in-store replacement at any Harbor Freight location.',
                                 'No single general warranty page was found on harborfreight.com; '
                                 'warranty terms are stated per product on official product pages '
                                 '(e.g., a 90-day guarantee against defects in materials and '
                                 'workmanship on many products).']},
  'logo_key': None,
  'logo_tile': None},
 {'name': 'Husky',
  'kind': 'retailer',
  'website': 'https://www.homedepot.com',
  'warranty_url': 'https://contentgrid.homedepot-static.com/hdus/en_US/DTCCOMNEW/fetch/Global_Assets/PDFs/Husky-Warranties-FINAL-v2.pdf',
  'warranty_phone': None,
  'customer_service_phone': '1-888-HD-HUSKY',
  'phones': [{'label': 'Customer Service', 'number': '1-888-HD-HUSKY'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'Most products are returned to any Home Depot retail store with a '
                               'receipt for repair or replacement; for air tools, do not return to '
                               'the store — call Customer Service first and send the product '
                               'postage prepaid to the address provided by the Customer Service '
                               'Team.',
                       'notes': ['Hand tools/wrenches/pliers listed as Lifetime Warranty: if the '
                                 'product ever fails, bring it back and it will be replaced free.',
                                 'Many other categories carry 1-year, 2-year or 3-year limited '
                                 'warranties and require a receipt indicating proof of purchase.',
                                 'Air tools warranty requires a copy of the dated first-owner '
                                 'purchase receipt with model circled, plus serial number and '
                                 'month/year of manufacture.',
                                 'Warranty excludes incidental/consequential damages and failures '
                                 'due to misuse, abuse or normal wear and tear.']},
  'logo_key': None,
  'logo_tile': None},
 {'name': 'Kobalt',
  'kind': 'retailer',
  'website': 'https://www.lowes.com',
  'warranty_url': 'https://www.lowes.com/kobaltguarantee',
  'warranty_phone': None,
  'customer_service_phone': '1-888-3KOBALT',
  'phones': [{'label': 'Customer Service', 'number': '1-888-3KOBALT'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': "No mail-in address is published in Lowe's official Kobalt "
                               'guarantee — return the product to the place of purchase with valid '
                               'proof of purchase and the defective product will be repaired or '
                               'replaced at no charge.',
                       'notes': ["Kobalt tools: 'You should never have a problem with your Kobalt "
                                 'tools. However, if you do, return the item to the place of '
                                 "purchase for a free replacement. No questions asked.'",
                                 'Other Kobalt products are warranted to the original purchaser '
                                 'against defects in material and workmanship; return to the place '
                                 'of purchase with valid proof of purchase for repair or '
                                 'replacement at no charge, with maximum liability limited to the '
                                 'purchase price paid.',
                                 'The guarantee does not cover damage due to misuse or abuse, '
                                 'normal wear, improper maintenance, neglect, unauthorized '
                                 'repair/alteration, or expendable parts and accessories expected '
                                 'to become unusable after a reasonable period of use.',
                                 'The guarantee page states most Kobalt products manufactured '
                                 'after May 1, 2016 come with this guarantee package, specific '
                                 'terms vary by product (check packaging, manuals, or the product '
                                 'page on Lowes.com), and directs customers to see store or call '
                                 '1-888-3KOBALT for details.']},
  'logo_key': None,
  'logo_tile': None},
 {'name': 'Lisle Corporation',
  'kind': 'manufacturer',
  'website': 'https://www.lislecorp.com/',
  'warranty_url': '',
  'warranty_phone': None,
  'customer_service_phone': '(712) 542-5101',
  'phones': [{'label': 'Customer Service', 'number': '(712) 542-5101'}],
  'ship_to_name': 'Filter Crusher Warranty',
  'ship_to_address': '807 E. Main St.\nClarinda, IA 51632',
  'ship_to_scope': 'scoped',
  'ship_to_scope_note': 'Published for the Filter Crusher (76000) only — for other Lisle products, '
                        'call (712) 542-5101 first.',
  'warranty_process': {'gate': None,
                       'notes': ['No general brand warranty page was found on lislecorp.com; '
                                 'warranty terms are published in individual official product '
                                 'documents.',
                                 'The ship-to address above is published in the official Filter '
                                 'Crusher (76000) document ONLY: send the product UPS Prepaid with '
                                 'a receipt or other proof of purchase date and a brief '
                                 'description of the problem.',
                                 "That document's coverage: one year from original purchase by the "
                                 'first purchaser; Lisle will repair or replace, free of charge, '
                                 'any part defective in materials or workmanship.',
                                 'No separate warranty phone is published — the warranty document '
                                 'and the Contact Us page both use (712) 542-5101.']},
  'logo_key': 'platform/logos/lisle.svg',
  'logo_tile': None},
 {'name': 'Mac Tools',
  'kind': 'manufacturer',
  'website': 'https://www.mactools.com',
  'warranty_url': 'https://www.mactools.com/pages/warranty-and-returns',
  'warranty_phone': None,
  'customer_service_phone': '1-800-MAC-TOOLS (622-8665)',
  'phones': [{'label': 'Customer Service', 'number': '1-800-MAC-TOOLS (622-8665)'}],
  'ship_to_name': 'Consumer Warranty Returns, Mac Tools',
  'ship_to_address': '4380 Old Roberts Road\nColumbus, OH 43228',
  'ship_to_scope': 'general',
  'ship_to_scope_note': None,
  'warranty_process': {'gate': None,
                       'notes': ['Warranty items are evaluated and those accepted under the Mac '
                                 'Tools Warranty will be replaced; allow 2 to 3 weeks for '
                                 'processing and replacement (officially published turnaround).',
                                 'All returns should include a list of the tools being returned '
                                 '(item numbers or a description), plus your name, address, and '
                                 'phone number — items cannot be returned to a PO Box, a physical '
                                 'address is required; keep your tracking number.',
                                 'A Material Return Authorization (MRA) is required for returns of '
                                 'mactools.com purchases — contact Mac Tools at 800-MAC-TOOLS; Mac '
                                 'Tools provides a limited warranty on its manufactured products '
                                 'to the original purchasing owner against deficiency in material '
                                 'or workmanship, with the period varying by product.']},
  'logo_key': 'platform/logos/mac-tools.png',
  'logo_tile': 'dark'},
 {'name': 'Matco Tools',
  'kind': 'manufacturer',
  'website': 'https://www.matcotools.com',
  'warranty_url': '',
  'warranty_phone': None,
  'customer_service_phone': '866-289-8665 (866-BUY-TOOL)',
  'phones': [{'label': 'Customer Service', 'number': '866-289-8665 (866-BUY-TOOL)'}],
  'ship_to_name': 'Matco Tools Warranty Service Department',
  'ship_to_address': '4403 Allen Road\nStow, OH 44224-1096',
  'ship_to_scope': 'general',
  'ship_to_scope_note': None,
  'warranty_process': {'gate': None,
                       'notes': ['No general warranty page was found on matcotools.com; warranty '
                                 'terms are published per product in official Matco manuals and '
                                 'vary by product (e.g., a one-year limited warranty in the '
                                 'MTJF1000 transmission jack manual and for Silver Eagle SE-series '
                                 'air tools).',
                                 'The ship-to address above is published in official Matco product '
                                 'manuals for warranty returns, freight prepaid; for SE-series air '
                                 'tools Matco instead directs returns to any Silver Eagle '
                                 'Authorized Warranty Center, freight prepaid.',
                                 'Proof of purchase is required for SE-series air tool repairs: '
                                 'include a copy of proof of purchase and a brief description of '
                                 'the problem; repaired tools are returned freight prepaid.',
                                 "Matco's official blog directs customers to their local "
                                 'distributor or its Customer Care team at 866-BUY-TOOL.']},
  'logo_key': 'platform/logos/matco.svg',
  'logo_tile': None},
 {'name': 'Milwaukee Tool',
  'kind': 'manufacturer',
  'website': 'https://www.milwaukeetool.com',
  'warranty_url': 'https://www.milwaukeetool.com/Support/Registration-and-Warranty',
  'warranty_phone': None,
  'customer_service_phone': '1.800.SAWDUST (1.800.729.3878)',
  'phones': [{'label': 'Customer Service', 'number': '1.800.SAWDUST (1.800.729.3878)'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No single mail-in address is published — warranty service requires '
                               'return of the product to a MILWAUKEE factory Service Center '
                               'location or MILWAUKEE Authorized Service Station, freight prepaid '
                               'and insured, located via the Find a Service Center page / eService '
                               'or by calling 1.800.SAWDUST (1.800.729.3878).',
                       'notes': ['Warranty registration is not necessary — a tool bought from an '
                                 'authorized Milwaukee distributor automatically comes with '
                                 'warranty coverage; keeping the receipt is recommended.',
                                 "The tool's date code is used to determine if it is within the "
                                 'warranty period; a copy of the invoice or bill of sale assists '
                                 'verification, and a copy of proof of purchase should be included '
                                 'with a returned product.',
                                 'Service is routed through factory Service Centers / Authorized '
                                 'Service Stations or the eService center '
                                 '(service.milwaukeetool.com) — no single published mail-in '
                                 'address.',
                                 'Power tools generally carry a 5-year limited warranty for '
                                 'defects in material or workmanship; other categories (batteries, '
                                 'hand tools, test & measurement, etc.) have separate terms '
                                 'published on the warranty page.']},
  'logo_key': 'platform/logos/milwaukee.png',
  'logo_tile': None},
 {'name': 'OEMTOOLS (GreatNeck Tools LLC)',
  'kind': 'manufacturer',
  'website': 'https://greatnecktools.com',
  'warranty_url': 'https://greatnecktools.com/pages/warranty-policy',
  'warranty_phone': None,
  'customer_service_phone': None,
  'phones': [],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No mail-in is required: file a claim by submitting a return '
                               'authorization request and providing a photo of the tool — the '
                               "official warranty page states 'no need to mail it in' and that "
                               'GreatNeck covers shipping costs for the replacement item.',
                       'notes': ['Most GreatNeck tools are backed by a Limited Lifetime Warranty: '
                                 'repair or replacement with a tool of equal or greater value; '
                                 'replacement parts shipped within the United States and Canada '
                                 '(warranty page also states U.S. only in one section).',
                                 "No receipts needed — 'You don't have to keep proof of "
                                 "purchase—ownership is enough'; registering the tool is "
                                 'recommended to make claims quicker.',
                                 'No customer-service phone number was published on the official '
                                 'greatnecktools.com pages checked (warranty policy, warranty '
                                 'registration, contact-us and homepage); the contact page offers '
                                 'a web/email form only.']},
  'logo_key': 'platform/logos/oemtools.jpg',
  'logo_tile': None},
 {'name': 'OTC',
  'kind': 'manufacturer',
  'website': 'https://www.otctools.com',
  'warranty_url': 'https://www.otctools.com/sites/default/files/576179_reva.pdf',
  'warranty_phone': None,
  'customer_service_phone': '800-533-6127',
  'phones': [{'label': 'Customer Service', 'number': '800-533-6127'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No mail-in warranty ship-to address is published in the official '
                               'OTC/Bosch warranty statement; it directs users to call Bosch '
                               'Technical Support at (888) 789-2602 with questions or prior to '
                               'sending in a product for repair.',
                       'notes': ['Warranty statement is by Bosch Automotive Service Solutions for '
                                 'OTC products: OTC Encore carries a Lifetime Limited Warranty '
                                 'only for buyers who purchase and continuously maintain an '
                                 'uninterrupted Encore software subscription; otherwise 1-year, '
                                 'with 90 days for refurbished units, batteries, cables, adapters '
                                 'and power supplies.',
                                 'Buyer must register the product within 30 days of purchase, all '
                                 'claims must be made within the warranty period, and proof of '
                                 'purchase must be supplied.',
                                 'Warranty does not cover freight to return the product to Bosch, '
                                 'consumables, or products abused, altered, opened, worn out or '
                                 'used inconsistently with instructions.',
                                 'Official OTC publication lists OTC and Robinair Customer Service '
                                 'as 800 533-6127 (Option 1); the call-before-sending number in '
                                 'the warranty statement is Bosch Technical Support (888) '
                                 '789-2602.']},
  'logo_key': 'platform/logos/otc.png',
  'logo_tile': None},
 {'name': 'PROTO Industrial Tools',
  'kind': 'manufacturer',
  'website': 'http://www.protoindustrial.com',
  'warranty_url': 'http://www.protoindustrial.com/support/warranty',
  'warranty_phone': None,
  'customer_service_phone': '800-800-TOOL',
  'phones': [{'label': 'Customer Service', 'number': '800-800-TOOL'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No general mail-in warranty ship-to address is published on the '
                               'official warranty page; torque products can be repaired and '
                               'recalibrated at any PROTO or DEWALT Factory Service Center or '
                               'other location designated by PROTO.',
                       'notes': ['Limited Lifetime Warranty: PROTO Industrial Tools, a business '
                                 'unit of Stanley Black & Decker, Inc., warrants PROTO-branded '
                                 'products for as long as the original purchaser owns the product '
                                 'against defects in material or workmanship.',
                                 '1-Year Limited Warranty for die grinders, torque wrenches, '
                                 'torque multipliers and torque testers; calibration warranted 90 '
                                 'days.',
                                 '2-Year Limited Warranty stated for air impact tools.',
                                 'Official PROTO news pages state for more information call '
                                 '800-800-TOOL or visit www.protoindustrial.com.']},
  'logo_key': None,
  'logo_tile': None},
 {'name': 'SK Tools USA, LLC',
  'kind': 'manufacturer',
  'website': 'https://sktools.com',
  'warranty_url': 'https://sktools.com/pages/warranty-and-exchanges',
  'warranty_phone': None,
  'customer_service_phone': '800-822-5575',
  'phones': [{'label': 'Customer Service', 'number': '800-822-5575'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'All warranty claims must be processed using the online form first '
                               '— items sent in without prior approval will not be processed and '
                               "will be returned at the customer's expense.",
                       'notes': ['Limited Lifetime Warranty for expected life of the tool against '
                                 'defects in materials and workmanship; 1-year exception for '
                                 'storage products, tool carts, torque products and consumables.',
                                 "Exclusive remedy is repair, replacement or refund at SK's option "
                                 'if the tool is returned to an authorized SK warranty '
                                 'provider/dealer.',
                                 'Customer is responsible for all shipping charges for returns, '
                                 'replacements and denied claims.',
                                 'Torque product factory repair uses different service centers — '
                                 'contact customerservice@skhandtool.com for the appropriate '
                                 'center.']},
  'logo_key': 'platform/logos/sk-tools.png',
  'logo_tile': None},
 {'name': 'SUNEX Tools Inc.',
  'kind': 'manufacturer',
  'website': 'https://sunextools.com',
  'warranty_url': 'https://sunextools.com/pages/test-forms',
  'warranty_phone': '877.786.3939',
  'customer_service_phone': '1.800.833.7869',
  'phones': [{'label': 'Customer Service', 'number': '1.800.833.7869'},
             {'label': 'Warranty Service', 'number': '877.786.3939'}],
  'ship_to_name': 'SUNEX Tools',
  'ship_to_address': '315 Hawkins Rd.\nTravelers Rest, SC 29690',
  'ship_to_scope': 'general',
  'ship_to_scope_note': None,
  'warranty_process': {'gate': None,
                       'notes': ['SUNEXPRESS warranty for impact sockets and hand tools: Lifetime '
                                 'Warranty, return shipping is NOT required — a replacement will '
                                 'be sent after approval of receipt and product failure.',
                                 'General warranty policy: return equipment or tools to SUNEX '
                                 'Tools or an Authorized SUNEX Warranty Center, shipping prepaid, '
                                 'including name, address and contact information, proof of '
                                 'purchase date, and a description of the suspected defect.',
                                 'Lifting equipment, air tools, tool storage and shop products '
                                 'carry 1-year warranties (some heavy-duty air tools 2 years).',
                                 'Contact page lists Service: 877.786.3939, Toll Free: '
                                 '1.800.833.7869, and a separate Mailing Address: 1491 E Poinsett '
                                 'Street Extension, Greer, SC 29651 (corporate mailing — the '
                                 'warranty ship-to is the Travelers Rest address from the official '
                                 'product manual).']},
  'logo_key': 'platform/logos/sunex.svg',
  'logo_tile': None},
 {'name': 'Snap-on Incorporated',
  'kind': 'manufacturer',
  'website': 'https://www.snapon.com',
  'warranty_url': 'https://www.snapon.com/Terms-and-Conditions-of-Sale',
  'warranty_phone': None,
  'customer_service_phone': '1-877-762-7664',
  'phones': [{'label': 'Customer Service', 'number': '1-877-762-7664'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'RGA required — contact the Snap-on Customer Care Center first '
                               '(1-877-762-7664 or ncccsupport@snapon.com); once the request is '
                               'validated you are provided an RGA number and sent a shipping label '
                               'to ship the product to Snap-on. The Kenosha warranty-information '
                               'address published on the site explicitly cannot be used for '
                               'warranty service.',
                       'notes': ['Professional-use warranty service is obtained by returning '
                                 'products to a Snap-on franchisee or representative; customers '
                                 'not serviced by a franchisee contact the Customer Care Center '
                                 'via the Contact Us section at snapon.com.',
                                 'Proof of purchase is required: warranty requests must include '
                                 '(1) date and proof of purchase, (2) where the product was '
                                 'purchased, (3) full name, (4) shipping address, (5) phone '
                                 'number, (6) email address, and (7) item number(s) or approximate '
                                 'package weight — requests missing information will not be '
                                 'processed.',
                                 "Warranty duration depends on each product's warranty code; "
                                 'consumable products are warranted only against defects in '
                                 'workmanship or materials at the time of sale.']},
  'logo_key': 'platform/logos/snapon.png',
  'logo_tile': None},
 {'name': 'Tekton, Inc.',
  'kind': 'manufacturer',
  'website': 'https://www.tekton.com',
  'warranty_url': 'https://www.tekton.com/our-warranty',
  'warranty_phone': None,
  'customer_service_phone': '616-214-8887',
  'phones': [{'label': 'Customer Service', 'number': '616-214-8887'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'No mail-in is required — submit a photo warranty claim online at '
                               'tekton.com/warranty and Tekton ships the replacement to you; no '
                               'ship-to warranty address is published (the Grand Rapids address on '
                               'the site is its company/support address, not a mail-in warranty '
                               'address).',
                       'notes': ['Photo-claim option: the official warranty form asks you to '
                                 'attach one or more images of each damaged tool, with the item '
                                 'number and a description of what went wrong; including your name '
                                 "and today's date in the image can speed verification.",
                                 "No receipts and no time limits: 'If you own the tool, our "
                                 "support comes with it,' and Tekton covers shipping on "
                                 'replacement items within the United States and Canada.',
                                 'Turnaround officially published on the warranty form: if a '
                                 'request is received before 2 p.m. ET on a weekday with all '
                                 'needed information, Tekton will ship a replacement the same day; '
                                 'if a tool is discontinued without a direct replacement, it '
                                 "issues a credit greater than the tool's last MSRP."]},
  'logo_key': 'platform/logos/tekton.svg',
  'logo_tile': None},
 {'name': 'Wright Tool Company',
  'kind': 'manufacturer',
  'website': 'https://wrighttool.com',
  'warranty_url': 'https://wrighttool.com/support',
  'warranty_phone': None,
  'customer_service_phone': '1.800.321.2902',
  'phones': [{'label': 'Customer Service', 'number': '1.800.321.2902'}],
  'ship_to_name': None,
  'ship_to_address': None,
  'ship_to_scope': None,
  'ship_to_scope_note': None,
  'warranty_process': {'gate': 'Contact your Wright Tool distributor for the warranty policy and '
                               'replacement process, or contact Wright Tool Customer Service at '
                               '800.321.2902; for torque wrenches, contact Customer Service for '
                               'repair locations and shipping instructions before returning.',
                       'notes': ['Limited lifetime warranty: for as long as you own it, any Wright '
                                 'Tool-manufactured product that fails due to defect in '
                                 'workmanship or materials will be replaced at no charge.',
                                 'Excludes defects caused by improper use, accident, abuse, '
                                 'alteration, neglect or normal wear.',
                                 'Torque wrenches carry a separate 1-year warranty and must be '
                                 'returned postage/freight prepaid accompanied by a dated copy of '
                                 'the sales receipt, invoice or purchase order.',
                                 'Support page also lists local phone 330.848.0600 and toll-free '
                                 'fax 1.800.543.2095 at One Wright Drive, PO BOX 512, Barberton, '
                                 'OH 44203 USA — that address is published as a contact address, '
                                 'not as a general warranty ship-to address.']},
  'logo_key': 'platform/logos/wright-tool.svg',
  'logo_tile': None}]

_CORPORATE_FIELDS = (
    "kind", "warranty_url", "warranty_phone", "ship_to_name",
    "ship_to_address", "ship_to_scope", "ship_to_scope_note",
    "warranty_process", "logo_key", "logo_tile",
)


def _companies_table():
    return sa.table(
        "dealer_companies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("owner_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("email", sa.String),
        sa.column("website", sa.String),
        sa.column("address", sa.Text),
        sa.column("phones", postgresql.JSONB),
        sa.column("notes", sa.Text),
        sa.column("is_directory", sa.Boolean),
        sa.column("kind", sa.String),
        sa.column("warranty_url", sa.String),
        sa.column("warranty_phone", sa.String),
        sa.column("ship_to_name", sa.String),
        sa.column("ship_to_address", sa.Text),
        sa.column("ship_to_scope", sa.String),
        sa.column("ship_to_scope_note", sa.Text),
        sa.column("warranty_process", postgresql.JSONB),
        sa.column("logo_key", sa.String),
        sa.column("logo_tile", sa.String),
    )


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _same_number(a: str, b: str) -> bool:
    """Same phone line, tolerating the formats official sites mix:
    a leading country-code 1, and vanity suffixes like
    "866-289-8665 (866-BUY-TOOL)" whose digits run past the real
    number. Equal after the leading-1 strip, or one a prefix of
    the other, counts as the same line."""
    da, db = _digits(a), _digits(b)
    if len(da) == 11 and da.startswith("1"):
        da = da[1:]
    if len(db) == 11 and db.startswith("1"):
        db = db[1:]
    if not da or not db:
        return False
    return da == db or da.startswith(db) or db.startswith(da)


def seed_corporate_directory(conn) -> None:
    """Idempotent upsert of the 23 verified directory brands,
    matched by name among platform rows (owner_id NULL)."""
    companies = _companies_table()
    existing = {
        row.name: row
        for row in conn.execute(
            sa.select(companies).where(companies.c.owner_id.is_(None))
        )
    }
    for seed in _SEED:
        corporate = {key: seed[key] for key in _CORPORATE_FIELDS}
        row = existing.get(seed["name"])
        if row is None:
            conn.execute(
                companies.insert().values(
                    id=uuid.uuid4(),
                    owner_id=None,
                    name=seed["name"],
                    email="",
                    website=seed["website"],
                    address="",
                    phones=seed["phones"],
                    notes="",
                    is_directory=True,
                    **corporate,
                )
            )
            continue
        # Existing directory row (the 0016 four): fill corporate
        # fields only, and make sure the customer-service number is
        # among its department phones (matched on digits, so format
        # variants don't duplicate).
        values = dict(corporate)
        cs = seed["customer_service_phone"]
        if cs:
            phones = [dict(p) for p in (row.phones or [])]
            if not any(_same_number(p.get("number", ""), cs) for p in phones):
                phones.append({"label": "Customer Service", "number": cs})
                values["phones"] = phones
        # Match on the upsert key (name among platform rows), not
        # the id: UUID storage format differs across dialects, the
        # name is the identity this seed guarantees.
        conn.execute(
            companies.update()
            .where(companies.c.name == seed["name"])
            .where(companies.c.owner_id.is_(None))
            .values(**values)
        )


def upgrade() -> None:
    op.add_column(
        "dealer_companies",
        sa.Column(
            "kind", sa.String(20), nullable=False, server_default="manufacturer"
        ),
    )
    op.add_column(
        "dealer_companies",
        sa.Column("warranty_url", sa.String(500), nullable=False, server_default=""),
    )
    op.add_column(
        "dealer_companies", sa.Column("warranty_phone", sa.String(100))
    )
    op.add_column(
        "dealer_companies", sa.Column("ship_to_name", sa.String(300))
    )
    op.add_column(
        "dealer_companies", sa.Column("ship_to_address", sa.Text)
    )
    op.add_column(
        "dealer_companies", sa.Column("ship_to_scope", sa.String(20))
    )
    op.add_column(
        "dealer_companies", sa.Column("ship_to_scope_note", sa.Text)
    )
    op.add_column(
        "dealer_companies",
        sa.Column(
            "warranty_process",
            postgresql.JSONB(none_as_null=True),
        ),
    )
    op.add_column(
        "dealer_companies", sa.Column("logo_key", sa.String(500))
    )
    op.add_column(
        "dealer_companies", sa.Column("logo_tile", sa.String(20))
    )
    seed_corporate_directory(op.get_bind())


def downgrade() -> None:
    # The seeded brands and their corporate data go with the
    # columns; the 4 pre-existing companies keep their identity
    # fields, exactly as 0016 left them.
    for column in (
        "logo_tile", "logo_key", "warranty_process", "ship_to_scope_note",
        "ship_to_scope", "ship_to_address", "ship_to_name",
        "warranty_phone", "warranty_url", "kind",
    ):
        op.drop_column("dealer_companies", column)
