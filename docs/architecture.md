# Architecture — M2

```text
Fixture preview -> public GET /api/demo -> fictional files (no SQL import)
Protected APIs -> Origin/fetch metadata -> local session + write CSRF
               -> server workspace/source context -> scoped SQL repositories
Future ingest -> SQLite transaction: Email + VectorDocument + IndexOutbox
              -> manual IndexWorker -> idempotent revision-aware IndexWriter
              -> ACK current revision -> SQL eligibility filtering
Processing -> source/purpose/provider consent gate -> Fixture/CompatibleProvider
           -> post-call policy check -> future structured pipeline
Embedding -> local-only gate -> independent local provider contract
```

12 application tables plus Alembic version table. Migration 0001 is a frozen snapshot, tested for upgrade/downgrade/re-upgrade in an empty temporary database. Tests compare migrated schema to ORM metadata. UTC storage rejects naive times and restores timezone-aware values on reads.

Repositories apply source/workspace filters in SQL; composite foreign keys protect ownership references. Active source is per-session, not a global row. APIs serialize allowed fields only, never credential_ref or arbitrary configuration.

Outbox claims use atomic UPDATE/RETURNING, lease tokens and expiry. Crashes replay idempotently within the attempt limit. Failure text is discarded. Stale document versions, generation changes and unavailable sources cannot become searchable. Writer durability/idempotency and physical cleanup are separate contracts; SQL and FAISS are not a single transaction. M2 starts no worker.

LLM and embedding protocols are separate. Compatible HTTP replies are bounded; provider requests reject redirects and environment proxies. Public DNS resolution is pinned with original TLS SNI/Host intact. Gates run before dispatch and before returning. Actual model weights, FAISS, ingestion, SMOA and connectors arrive in subsequent milestones.

Protected API scaffold:

- POST/GET/DELETE /api/session: establish/read/revoke local session.
- GET/POST /api/sources: own-workspace metadata, connectors disabled.
- POST /api/sources/{id}/activate: per-session selection.
- GET/PATCH /api/sources/{id}/policy: typed scope and versioned policy update.
- GET /api/emails, /api/emails/{id}, /api/events, /api/index-status: session and current-source header required. No import/sync/inference routes yet.

Full source/model management UI remains M3–M5. Current settings show foundation startup status; the public preview does not pretend to come from configured real sources.
# M3 ingestion extension

Browser binary upload → bounded text-only MIME decoder → session/source-bound
memory preview → explicit selection → scoped per-mail transactions → normalized
mail and validated candidates → durable index outbox. The default import mode is
browse; rule extraction is an explicit local fallback. Model reprocessing uses the
existing ProcessingGateway and validates JSON/evidence before committing results.

Canonical hashes and sender-scoped Message-ID hashes deduplicate within a source.
Import timestamps are distinct from nullable original received timestamps. Migration
0002 adds import/extraction metadata with native SQLite column operations, avoiding
table recreation that could cascade-delete referenced data. Main dashboard fixtures
remain isolated from private import results until M4.

## M4 source-aware views

The first-use screen requires explicit source choice. A source-bound `/api/dashboard`
snapshot supplies 50-item email/event pages and source-wide counts under a SQLite
read transaction. Body text is fetched only for an opened mail detail; summaries
and event evidence still contain derivative mail content. Local flag writes are
scoped, CSRF-protected and independent of content/index revisions.

Header source selection controls the calendar, email, assistant and settings views.
Requests bind to their initiating source; source switching clears UI detail/chat
and server-side previews. Full conversation and mobile panel views reuse mounted
components. Shortcuts use visible-page data directly, not an LLM or vector search.
Provider status exposes configured mode/host without credentials; consent saves
continue through the versioned M2 gate. No migration beyond 0002 is needed for M4.
