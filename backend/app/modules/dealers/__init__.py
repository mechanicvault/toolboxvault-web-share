"""Dealers module (item structure package, owner 2026-10-18:
"this dealer stuff, as integrated as it will be, should still be a
module — add, edit or remove at anytime").

The dealer DIRECTORY (platform companies with published corporate
contacts), users' PRIVATE companies and agent records, and PREFERRED
agents per user x company. Item dealer tags live on the inventory
records as a bare FK; when this module is off for a user the tags
hide everywhere and inventory keeps working untouched.

Agent signup/profiles/public visibility is the later Dealer Portal
build — not here. Depends on core ONLY; inventory must never depend
on this module.
"""
