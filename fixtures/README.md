# Fictional public fixtures

Original authored examples only. No real mailbox, student identity, credential,
or copied course email appears in this corpus. Senders use reserved example.org.

| File | Purpose |
|---|---|
| manifest.json | Schema version, frozen evaluation clock, fictional marker |
| emails.json | 30 unique IDs, 10 emails in each category |
| extractions.json | 26 gold annotations, not generated model outputs |
| profile.json | One explicitly fictional profile |
| failures.json | Four future fault-injection specifications, not execution results |
| schemas/ | JSON schemas exported from validated backend contracts |

The duplicate notice a10 repeats a02's body without duplicating its event.
The updated NLP deadline a03 replaces a01; the original event is superseded.
Unknown dates remain needs_confirmation. Date-only deadlines have no guessed time.
The d09 malicious instruction is untrusted text for testing, never executable input.
The preview shifts all fictional calendar dates coherently; it never changes these files.

Run `python scripts/manage.py validate` at the repository root. Full ingestion,
repair and safety evaluation happens in later milestones, not M1.
