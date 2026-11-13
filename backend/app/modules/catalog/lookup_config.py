"""Operator setting keys for the lookup chain's external
layers (wave 4). A leaf module — constants only — so core's
admin routes can import the keys without pulling the catalog
module (and its dependency graph) into core.

External layers follow the AI seam's pattern (Admin ->
Settings): a provider name + the NAME of the environment
variable holding the API key. The key itself never enters
the database. A layer with a missing leg is DARK: the chain
skips it silently and answers from the layers that remain.

The general web search is NOT one of these layers anymore:
since the owner's one-vendor decision (2026-10-25) the AI
provider's own web search (billing.ai_service.web_search) is
the site's only search — it rides the AI provider/model/key
settings and has no separate configuration of its own.
"""

# UPC / barcode database (catalog.lookup's second layer).
UPC_PROVIDER_KEY = "lookup.upc_provider"
UPC_API_KEY_REF_KEY = "lookup.upc_api_key_ref"
