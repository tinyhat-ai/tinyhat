---
name: tinyhat-mail-client
description: "Help the owner open Mail on their Tinyhat desktop or connect their agent mailbox to Thunderbird, Apple Mail, Epistles, or another IMAP/SMTP client. Use for 'open your email app' or 'set up this mailbox on my laptop'; not for reading messages, sending mail, connecting an existing Gmail inbox via OAuth, or renaming the address."
---

# Open your Tinyhat inbox

On a compatible Computer, the **Mail** desktop shortcut opens Thunderbird with
the agent mailbox already configured. Use `tinyhat:tinyhat-computer-desktop` to
open the Computer when needed. The client software is included in the image;
do not install packages during assignment or invent a working shortcut on an
older runtime. Before promising it, check only that
`/usr/local/bin/tinyhat-mail` is executable, `~/Desktop/Tinyhat Mail.desktop`
exists, and `~/.config/tinyhat/mail/settings.json` exists. Do not read the settings
file into the transcript. If any are absent, report that Mail setup is pending
or the Computer needs a compatible image.

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

On the Computer, use the existing authenticated platform client to request
`POST /hapi/v2/computers/me/email/client-credentials`. Keep the response inside
one process that writes it directly into a private file. Do not run a raw HTTP
command that prints the response. Never ask the owner to paste credentials.

Run this from the installed plugin package root (the directory containing
`hermes.plugin.json` and `platform.py`), using the Computer's Python:

```sh
python - <<'PYTHON'
import importlib.util, json, os, sys, tempfile
from pathlib import Path
output = None
try:
    spec = importlib.util.spec_from_file_location("tinyhat_mail_export", "platform.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    client, _ = module.build_platform_client()
    settings = client.post_json("/hapi/v2/computers/me/email/client-credentials", {})
    for directory in (Path.home()/".config", Path.home()/".config/tinyhat",
                      Path.home()/".config/tinyhat/mail-client"):
        if directory.is_symlink():
            raise ValueError("Unsafe export directory")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != os.getuid():
            raise ValueError("Unexpected directory owner")
        directory.chmod(0o700)
    fd, output = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=directory)
    with os.fdopen(fd, "w") as file:
        json.dump(settings, file)
    print("Private settings saved:", output)
    print("SMTP enabled." if settings.get("smtp_enabled") else "SMTP is not enabled.")
except Exception:
    if output:
        Path(output).unlink(missing_ok=True)
    print("Private mail setup failed; no credentials displayed.", file=sys.stderr)
    sys.exit(1)
PYTHON
```

Never `cat`, echo, or re-read that file into the transcript. The owner can open
it themselves through the desktop and enter the settings into their client.
Delete the export after use. The file lives on this Computer, not automatically
on their laptop; do not upload it to a sharing service or send it by chat/email.

For setup directly on the owner's laptop, their coding agent can call
`POST /hapi/v2/agents/{agent_id}/email/client-credentials` with its existing
account token. Apply the same single-process private-file/client-store rule
there. Never transfer a Computer identity token to the laptop or ask the cloud
agent to collect an owner sign-in code.

`SMTP enabled` above comes from `smtp_enabled` in the **client-credentials
response**. Its `sending: owner_only` permits only `allowed_recipient`; these
fields are separate from `tinyhat_mail status`, which calls the recipient
`owner_email`. If SMTP is disabled, explain that setup is pending. Do not bypass
policy with another account, JMAP submission, or a different server.

After a confirmed address change, fully close and reopen Mail so it loads the new username.
Existing messages and drafts remain in the same profile. The old address stops
receiving after the disclosed 24-hour overlap; do not delete the mail profile.

## Server-managed delivery

Clients always connect to Tinyhat's own mail server with their mailbox login.
The server controls outbound delivery and the original-mailbox Reply-To. Never
request or install provider credentials on the Computer, or configure a delivery
provider's SMTP host in the owner's client. Owner-only sending remains enforced.

Gmail mobile supports adding external IMAP accounts. Gmail web is removing
external POP/Gmailify and SMTP Send as, so do not promise permanent Gmail web
compatibility. Offer a standard IMAP/SMTP client when that option is unavailable.
