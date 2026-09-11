# Individual owner account upgrade

Adds the `tinyhat-account-upgrade` skill and `tinyhat_account_upgrade` tool for
existing customers on assigned cloud Computers. The platform derives the owner;
no account IDs or laptop tokens are supplied. A single express human approval
covers terms, sharing, and identity verification. Paid-service activation and
provider purchases remain separate.

Verification: package validator, full unittest suite, and compileall. The tool
tests cover schema/adapter registration, current-owner routes, strictly affirmative
consent, injected account IDs, sanitized errors, unverified owner guidance and
verification URL restrictions. Platform HTTP/DB tests separately exercise the
actual assignment and membership boundary, revoked email proof, and resumable
Stripe setup using local fixtures. No real Stripe or cloud purchase is tested.

Release requires compatible platform APIs to be deployed first. No runtime or
release/channel change is included. On older or disabled platforms, report
unavailable and do not collect personal details or approvals.
