# Changelog

Dated build history lives here and in commit messages — not in
code comments. Code comments explain why the code works the way
it does; when something changes, the story of the change goes
in the commit that makes it (and, for anything a reader of the
project should know, a dated entry below).

## 2026-11-19 — Comment cleanup (sheet row 126)

Stripped the dated history notes out of the backend code:
owner-order / date / lane / package attributions removed from
comments and docstrings across `backend/app`, the largest
diary-style module headers rewritten to their standing rules,
and the quoted-rule headers restated as rules. Comments that
explain why the code works the way it does were kept. Every
stripped note's full text remains in this repository's commit
history, in the commits that introduced the code it described.
