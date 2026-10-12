# Privacy boundary — M2

Implemented protections:

- Loopback-only server and trusted Host checks. Protected requests reject mismatched Origin and cross-site/same-site fetch metadata. Unsafe protected requests require exact Origin; authenticated writes also require CSRF.
- HttpOnly, SameSite=Strict cookies scoped to /api, with one-hour expiry. HTTPS sets Secure; HTTP loopback does not. Sessions are in server memory and restart invalidates them. CSRF stays in client memory.
- Private responses are no-store. Actual request body size is capped at 256 KiB before parsing. Errors do not echo submitted values, keys, provider bodies or SQL values.
- Source reads bind to the server session workspace/selected source, and stale source headers fail. Composite foreign keys enforce workspace/source and event/email ownership.
- Cloud defaults off. Processing requires global enablement plus per-source consent matching mode, URL and model. Scope changes revoke consent unless explicitly re-authorized in that update.
- Local model URLs must be literal loopback addresses; localhost is canonicalized. Cloud uses HTTPS, verified public DNS addresses pinned with original Host/TLS SNI, no environment proxies or redirects.
- Remote embedding is rejected. No models or index workers start automatically. Tests use fictional inputs and mock providers/transports.

The fixture preview remains public read-only sample data, separate from private source storage. Preview stars/chat are browser-memory only. No telemetry exporter is configured. Package installation contacts registries; demo runtime needs no outside service.

Private SQLite/WAL storage lives in the user application directory, outside the source repository. It is not encrypted at rest; operating-system disk protection is the appropriate additional layer. Policies persist, session secrets do not. No source or actual mail is automatically imported. credential_ref is only a future reference field; it is not a credential storage implementation.

retain_body=false constrains subsequent ingestion calls; setting it does not yet purge historical data. Memory/profile default off. Historical cleanup, keyring credentials, connector authorization and full deletion remain later milestones and must be ready before their real-source workflows ship.

Index claims are leased and revision/generation-aware; only current acknowledged SQL documents may be retrieved. A concrete writer must enforce durable idempotency and old-version rejection. M2 tests the contract with an in-memory writer. FAISS, actual embedding weights and physical index deletion are not claimed implemented.

This is a single-person local application. Origin checks protect against hostile websites; local malware and OS administrators are outside the application's trust boundary. Keep the app on loopback. Revocation can block results and later calls, but cannot retract a request already sent to a provider.
# M3 local files

Local EML/MBOX import requires choosing a file, reviewing a memory-only preview,
and confirming selected messages. Raw files and attachments are not persisted;
normalized text is stored according to the selected source policy. HTML is text-only,
and importing or rule processing makes no provider calls. Memory previews expire
after ten minutes and cannot be reused across sessions or sources. Unknown mail
dates remain unknown rather than being assigned the processing date.

`retain_body=false` controls the normalized original body, not derivative summaries,
event evidence or index text. Full source erasure is a later milestone. Do not commit
runtime databases, user-selected mail, credentials or screenshots of private content.
The two tracked files under `fixtures/mail` are newly authored fictional samples.

See [M3 usage and limits](milestones/M3.md) for scope and processing behavior.

## M4 source selection and settings

Refresh requires explicit source selection before mail content is loaded. Switching
to another source or fictional preview clears mail/event detail, current chat and
memory previews. Requests are bound to the initiating source ID and rejected if
the session selection changes. Local stars/read flags persist only in SQLite.

The settings UI can change future import scope, body retention and provider-specific
cloud consent. Opening settings or using assistant shortcuts makes no model call.
Private mail, chat and source selection are not stored in browser localStorage or
sessionStorage. This does not imply encryption or retroactive content deletion.
See [M4](milestones/M4.md) for pagination scope and current limitations.

## Offline beta update (M5–M9)

IMAP/MCP configuration and sync are explicit manual actions. Session credentials
expire or optionally use the Windows vault. Disconnect does not revoke provider
credentials: do that at the provider. Actual account acceptance has not been run.

QA history and fixed-topic implicit interests require separate opt-ins. Disable
stops new records; use data management to clear retained history or interest signals.
Suggestions need acceptance. Cloud contact masking is best-effort and cannot remove
all identifying names or context. Provider-specific consent is still required.

Local lexical vectors persist in the private database and are fenced by source and
version. No model is downloaded automatically. Export is private JSON downloaded to
this computer. Deletion includes manually edited events and all derived records;
export first if needed. It blocks late writes, attempts WAL truncation and compaction,
and honestly reports pending maintenance. It cannot wipe provider mail, backups or
SSD remnants. See [M7](milestones/M7.md) for exact behavior.
