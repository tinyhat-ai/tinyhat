# Local email onboarding verification

The real Hermes gateway, Stalwart 0.16.15 and a bounded live model key ran against
a disposable owner mailbox. The owner received a welcome, replied over SMTP,
and received a generated response. Restarting Hermes did not duplicate either
message. Renaming preserved mailbox ID/history; the old alias was removed after
simulated expiry. The platform enforced the fixed verified-owner recipient.
All addresses shown are disposable fixtures.

![Actual received welcome](welcome.png)

The welcome arrived 9.54 seconds after the conversation test started; the reply
arrived at 26.86 seconds. These measure local email onboarding, not VM creation.
Internet delivery and production inbox placement have not been tested here.

Linux verification used a Python 3.13 container with Hermes installed, this
plugin and runtime, and an isolated HERMES_HOME. Public CLI discovery showed:

```text
hermes plugins list --plain --no-bundled
enabled      git      0.32.12  tinyhat
Linux config, public CLI discovery and email platform registration: passed
```

Runtime configuration was applied twice to verify idempotence, private file
permissions and preserved owner model settings. No upstream Hermes code was
modified. Compatible platform APIs and runtime/plugin versions are prerequisites
for rollout; this evidence does not claim a production release or deployment.

![Owner reply and actual Hermes response](conversation.png)

![Confirmed rename API result presented for review](rename.png)

The rename image presents API results; it is not a new user interface.
