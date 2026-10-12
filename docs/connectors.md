# Read-only connectors and MCP service research

Research date: 2026-10-12. No real mailbox was authorized during reconstruction;
the user requested offline acceptance first. Tests use authored fictional mail.

## IMAP

Configure an IMAP source with server, port (normally 993), username and an app
password appropriate for that provider. TLS certificates and hostname are verified;
DNS must resolve exclusively to public addresses and the socket pins one result.
Only IMAPS is supported (no plaintext LOGIN, STARTTLS fallback or OAuth refresh).
Selection is read-only and body fetches use BODY.PEEK. No flag, label, send, delete,
expunge or mailbox-write commands are exposed. See [Python IMAP documentation](https://docs.python.org/3.11/library/imaplib.html).

The selected folder must use ASCII / IMAP modified UTF-7 and belong to configured
scope. UIDVALIDITY resets trigger bounded rescan; identifiers include folder,
UIDVALIDITY and UID. Native dates stay unknown when the message Date is absent.
Unknown dates are excluded unless explicitly enabled. Header-date filtering follows
the source range, while IMAP SINCE uses the mailbox's internal date.

Sync is manual, at most 200 messages per run with bounded pages, no automatic polling.
Browse is default; local rule processing is explicit. SQL stores per-folder cursor
checkpoints. Interrupted pages may replay idempotently; cancellation discards the
in-flight result before persistence and stops subsequent reads. Network operations
have timeouts. Server restart records interrupted jobs instead of pretending success.

## MCP transport and normalized contract

Campus Flow supports bounded Streamable HTTP JSON/SSE responses and initialization,
tool discovery, session headers and explicit session termination. No third-party
process/stdio service is installed or started. Only explicitly configured loopback
HTTP(S) or public HTTPS endpoints are allowed; redirects, proxy environment variables,
URL credentials/query tokens and private-network DNS results are rejected.

Protocol references: [transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) and
[security guidance](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices).
Server descriptions, annotations, mail bodies and tool results do not grant permissions.

The first adapter expects **campusflow-mail-v1**. It calls only the selected allowlisted
list/read tool. Protocol discovery success is separate from usable mail schemas.
The account label is configured by the user; absent response identity is not independently
verified. If a response includes `account_id`, it must match. A token must be issued for
this MCP endpoint; upstream Gmail/Graph tokens must not be pasted as MCP credentials.
Automatic OAuth discovery, audience-signature validation and token refresh are not implemented.

List tool arguments: `{account_id, limit, recent_days, cursor?}`.
Output: `{account_id?, messages: [{id}], next_cursor: string|null}`.
Read arguments: `{account_id, id}`.
Output: `{account_id?, id, subject, sender, body_text, date_header?}`.
Return that object in `structuredContent` or a single JSON text content block.
IDs, text, page sizes and cursors are bounded; missing bodies/IDs cannot be invented.

## Services found

For offline protocol acceptance, start the authored fixture-only service with
`python scripts/manage.py mcp-demo --port 8990`. Configure a MCP source with endpoint
`http://127.0.0.1:8990/mcp`, account ID `fictional-demo` and public dummy token
`fictional-mcp-demo-token`. Enable unknown-date messages if you want all three samples.
This service reads only tracked fictional fixtures, never a real mailbox or private
directory. It is an independently started example service, not a hosted third-party
mail integration. HTTP JSON-RPC end-to-end is tested against its ASGI application.

| Service | Primary source / observed capabilities | Campus Flow compatibility |
| --- | --- | --- |
| Composio Gmail | [Toolkit](https://composio.dev/toolkits/gmail), [direct-tool sessions](https://docs.composio.dev/docs/sessions-via-mcp). Hosted MCP with OAuth; mail fetch and message read are available alongside write tools. | HTTP protocol candidate. Use a direct-tools session exposing only reads. Vendor argument/output mapping requires validation or a normalized bridge; not claimed tested. Meta-tool routers are rejected. |
| Composio Outlook | [Toolkit](https://composio.dev/toolkits/outlook). Hosted integration for Microsoft mail. | Candidate for read-only scoped configuration; vendor schemas/headers and tenant authorization require adapter validation. Not claimed plug-and-play. |
| GongRzhe Gmail MCP Server | [Repository](https://github.com/GongRzhe/Gmail-MCP-Server). Self-hosted Google OAuth, search/read and write functions. | Documented stdio deployment is not directly supported by this HTTP-only client. An operator-owned HTTP/normalized bridge and least-privilege OAuth setup are needed. Not installed or account-tested. |

These are researched candidates, not security endorsements or live-account acceptance.
Tool names alone cannot guarantee read-only behavior; upstream grants and the operator's
server implementation must also restrict access. A hosted service is another data processor.
Accounts, scopes, pricing and deployment options should be rechecked when connecting.

## Credentials and lifecycle

Secrets never enter model prompts, JSON source configuration, response objects,
browser persistent storage or error messages. Default storage is session memory;
expiry/logout/restart removes access and expired memory is purged periodically.
Optional persistence uses native [Windows Credential Manager](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew).
Other platforms currently use session-only mode; unavailable secure persistence fails
closed rather than writing plaintext files.

Pause cancels the current run and blocks new sync until explicit resume. Disconnect
removes local credentials and keeps local mail available. It does not pretend to
revoke tokens at Google, Microsoft or a third-party MCP operator; revoke their grants
at the respective account portal as needed. Source-wide deletion is a separate flow.

Offline acceptance covers IMAP command transcripts and bounds, MCP JSON/SSE/session
protocol, whitelist/schema/address checks, credentials redaction and sync/lifecycle
with fake transports. Windows native vault was exercised with an ephemeral fictional
credential and deleted afterwards. Real IMAP and third-party MCP mail remain untested.
