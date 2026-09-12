---
name: tinyhat-mail-client
description: "Help the owner open Mail on their Tinyhat desktop or connect their agent mailbox to Thunderbird, Apple Mail, Epistles, or another IMAP/SMTP client. Use for 'open your email app' or 'set up this mailbox on my laptop'; not for reading messages, sending mail, connecting an existing Gmail inbox via OAuth, or renaming the address."
---

# Open your Tinyhat inbox

On a compatible Computer, the **Mail** desktop shortcut opens Thunderbird with
the agent mailbox already configured. Use the existing desktop-access skill to
open the Computer when needed. The client software is included in the image;
do not install packages during assignment or invent a working shortcut on an
older runtime.

There are two welcome messages: Tinyhat sends a notice to the agent's inbox,
and the agent sends the owner a separate welcome. The owner replies to the
agent's welcome to start a Hermes conversation. The platform notice must not
be treated as an owner instruction or replied to automatically.

## Another email client

Explain that this is the agent's Tinyhat mailbox, separate from the owner's
Gmail or other sign-in inbox. Standard settings are full email address as
username, IMAP port **993** and SMTP port **465**, both with **SSL/TLS** and
normal password authentication. Use the server hostname supplied by Tinyhat;
do not guess it from the address or disable certificate validation.

A coding agent on the owner's laptop can explicitly request settings with
`POST /hapi/v2/agents/{agent_id}/email/client-credentials`, using the account
access token it already holds. The assigned Computer has the equivalent
`POST /hapi/v2/computers/me/email/client-credentials` endpoint. Never collect an
owner's sign-in code in the cloud agent or transfer a machine identity to a laptop.

Credentials are returned only to an authenticated owner or assigned Computer.
When the owner asks to configure a client, save them directly into that client's
credential store, or a private file outside any repository, with a 0700 parent
directory and 0600 file. Do not print the response into a transcript, copy it to
a project `.env`, send it by email/chat, or put credentials in a URL. For manual
setup, let the owner open the private file on their own device. Never upload it
to a sharing service. Delete a temporary export after the owner has saved it.

Check `smtp_enabled` before claiming sending works. If false, report that SMTP
submission is not enabled for this mailbox; do not bypass it with another
account, JMAP submission, or a different server. When `sending` is `owner_only`,
only `allowed_recipient` is permitted. Standard client access does not grant
permission to email other people.

After a confirmed address change, reopen Mail so it loads the new username.
Existing messages and drafts remain in the same profile. The old address stops
receiving after the disclosed 24-hour overlap; do not delete the mail profile.


The mail server may use an explicit Resend delivery route. Clients still use
only their Tinyhat mailbox login. The recipient sees an agent-specific verified
sender; Reply-To points to the original Tinyhat inbox. Never request or install
Resend credentials on the Computer, or configure a provider SMTP host in a
user's client. The verified-owner recipient restriction is unchanged.

Gmail mobile supports adding external IMAP accounts. Gmail web is removing
external POP/Gmailify and SMTP Send as, so do not promise permanent Gmail web
compatibility. Offer a standard IMAP/SMTP client when that option is unavailable.
