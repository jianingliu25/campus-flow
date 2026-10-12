# Security

Campus Flow offline beta is a loopback-only local application. Do not expose it
publicly. Use only fictional data in issues, fixtures and screenshots.

Source ownership is enforced by composite foreign keys and scoped reads. Local
sessions, exact Origin checks, CSRF tokens, DNS-pinned outbound connections, explicit
cloud-provider consent, read-only mail commands, opt-in memory and deletion barriers
have regression coverage. Credentials stay in an expiring session or the optional
Windows credential vault; there is no plaintext credential-file fallback.

Contact masking is best-effort, not anonymization. Names and context may remain.
Mailbox-provider token revocation must be completed at the provider. Local deletion
removes application records and attempts compaction; it does not erase backups or
certify forensic SSD wiping. Actual mailbox and learned-model acceptance is pending.

Do not post private mail, tokens or raw logs. Until a private reporting channel is
configured, open only a minimal issue asking for a private contact method, without
vulnerability reproduction details. No production support SLA is claimed.
