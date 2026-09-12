# Authenticated owner email

The email adapter now starts turns only for an exact verified-owner address and
one aligned DMARC pass from the managed receiving MTA. Other email stays in the
inbox without generating an agent turn or an automatic response. Raw headers
avoid MIME decoding of authentication claims. Duplicate From/result headers,
quoted/commented claims, failed results and missing evidence fail closed.
Retries recheck the source against the current owner; older pending turns that
have no authentication evidence are dropped. This includes owner mail queued
by the old plugin's header format during the upgrade: the owner must resend it.
Rejections log a fixed reason class at most once per minute, without message
contents, addresses or identifiers, so authentication drift is diagnosable.

The MTA must first strip supplied Authentication-Results and insert its own on
all SMTP paths, including submission. Install that server policy before releasing
this plugin. Never rely on a sender-supplied header with the server's hostname.
Mailbox credentials, server administration and Computer-local state are trusted;
this change does not defend against a compromised owner email account or stolen
mailbox credentials. The parser requires ASCII grammar and the final DMARC clause
emitted by Stalwart 0.16.15 with mail-auth 0.11.3; a changed formatter fails closed.
DMARC authenticates the domain through SPF/DKIM, while the
sending provider is responsible for enforcing the mailbox identity.

## Local evidence

A disposable Stalwart 0.16.15 server verified real SMTP messages against an
isolated SPF/DMARC DNS fixture. JMAP results went through this adapter and the
real Hermes SDK session dispatcher. The test replaced model execution with a
counting handler; it did not call a model or test response quality.

| Received mail | Hermes turns |
| --- | ---: |
| Verified owner | 1 |
| Spoofed owner | 0 |
| Forged authentication pass | 0 |
| Duplicate forged pass headers | 0 |
| Authenticated non-owner | 0 |
| Non-owner with owner Reply-To | 0 |
| Duplicate From | 0 |
| Verified owner with supplied authentication header | 1 |
| Authenticated submission with spoofed owner | 0 |
| Forged ARC assertion | 0 |
| Automatic reply | 0 |

All eleven messages remained in the inbox. Sender-supplied authentication
headers were removed; exactly one receiving-MTA result remained. Disposable
containers, volumes and network were removed after the run.

Package validation, byte compilation and 588 unit tests passed (one existing
skip). Additional regressions cover quoted/commented false claims, result
ambiguity, ASCII-only grammar, final-verdict ordering, private throttled rejection
logs, old queued/pending turns and owner changes during recovery.
No production deployment or release is claimed by this evidence.
