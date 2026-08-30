# ADR-002 — JWT over a server-side session store

**Status:** Accepted
**Date:** 2026-08-28

## Context

The admin audit panel (`frontend/admin-panel`) is the only authenticated surface in FinSense.
Everything else — the public dashboard and the ticker detail page — is anonymous. The audit
endpoints need to know *which* admin performed an action, because `audit_log` is immutable
(US-G4) and stores `admin_id` / `admin_name` on every entry.

Two options for carrying that identity between login and an audit write:

1. **Server-side sessions** — a session collection in MongoDB, an opaque cookie, one DB read per
   request to resolve it.
2. **Stateless JWT** — a signed token the client stores and replays as a bearer header, verified
   by signature alone.

## Decision

**JWT, HS256, access token only, 8-hour expiry.** No refresh token.

`docs/openapi.yaml` already declared `bearerAuth` with `bearerFormat: JWT` and defines no
`/auth/refresh` endpoint, so a session-cookie design would have meant changing the contract the
frontend types are generated from.

The token carries `sub` (= `admin_id`), `username`, and `display_name`. `display_name` is a claim
rather than a per-request lookup precisely because `audit_log` denormalises it — an audit write
must be able to name the actor without a second read of `admin_users`.

## Consequences

**Accepted cost: revocation is not immediate.** `require_admin` verifies the signature and does
not read `admin_users`, so setting `is_active: false` (via `scripts/seed_admins.py --deactivate`)
blocks *new* logins but leaves an already-issued token working until it expires. Worst case is
`JWT_EXPIRE_HOURS`. For a small internal team this is acceptable; the 8-hour expiry is the knob
that bounds it. If instant revocation ever becomes a requirement, the fix is a token-version
claim checked against the admin row — which reintroduces the per-request read this ADR avoided,
so it should be a deliberate revisit, not a quiet patch.

**`JWT_SECRET_KEY` has no default.** `_require_secret` raises rather than signing with an empty
key. A shipped default secret is a forgeable admin token, and this class of bug is silent.

**Rotating the secret logs everyone out.** That is the intended emergency lever.

**Algorithm is pinned on decode.** `decode_access_token` passes an explicit `algorithms` list
and never the algorithm the token names, which is what closes the `alg: none` forgery.
