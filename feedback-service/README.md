# Community feedback service

This Flask service collects independent ratings and reviews for public GitHub repositories. The current changes are prepared locally and have not been qualified for public production use.

## Rules and seal

- Each eligible GitHub account has one current rating and one current review per repository. Accounts must be at least 30 days old. Repository owners cannot rate their own repository or approve exceptions. The score is the arithmetic mean of eligible ratings; a rating linked to a hidden review is excluded while that review is hidden.
- The owner may write one public reply per review. Hiding a review requires an operator account, a report and one of these reasons: spam, personal data, harassment, or a security claim without evidence. The public moderation log shows decisions and reasons without hidden review text. Reports do not hide anything automatically. No moderator is configured by default.
- Security concerns require a same-repository GitHub file, line, issue or commit URL. The link format is checked; the service does not establish whether the evidence is true or reachable.
- Seal activation requires a signed-in GitHub administrator and a fresh GitHub permission check. A scheduled check records the first observed removal and the current average. GitHub errors and inaccessible READMEs are treated as failed checks, not proof of removal. The scheduled job must be configured and monitored separately; GitHub Actions schedules are best effort. Feedback stays public after removal.
- The badge signals the rules of this service, not an independently audited guarantee. One person can control multiple GitHub accounts; organization conflicts are not reliably detectable. The operator controls the software, signing key and database and can change data or what is displayed. A signed receipt and independently retained journal copy can expose some changes, but cannot prevent them or prove an account belongs to a unique person. Old entries are not retroactively signed. Operator-controlled mirrors and keys are not independent witnesses.
- Owner replies currently authenticate the individual GitHub owner ID; organization administrators cannot reply through that mechanism. The public moderation log returns the latest 100 decisions. There is no independent appeal channel.

## Local setup

Requires Python 3.10 or later. Install `requirements.txt` into a virtual environment. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in a secret manager or shell, and configure a GitHub OAuth callback of `http://127.0.0.1:8766/auth/callback`. Set `FEEDBACK_JOURNAL_PRIVATE_KEY` to the base64 encoding of a securely generated 32-byte Ed25519 private key. Store it privately and back it up separately: changing or losing it breaks verification of the existing journal. Never commit it. Start `python app.py` and open `http://127.0.0.1:8766/?repo=OWNER/REPO`.

Without a valid journal key, signed feedback, moderation and seal writes fail closed. Without OAuth credentials, sign-in is disabled. SQLite's `feedback.sqlite3` is ignored by Git. Run `python -m unittest discover -s tests -v` from this directory. Tests mock GitHub and do not establish a real sign-in or administrator permission flow.

GitHub sign-in uses state and PKCE; sessions use HttpOnly and SameSite=Lax cookies. Authenticated writes check the configured Origin and CSRF token and are rate limited. Access tokens are not persisted. Repository resolution depends on the GitHub API; outages or limits can prevent reads and writes.

## Journal, receipts and local mirror

New ratings, reviews, owner replies, moderation decisions and seal changes are chained and signed with the service's Ed25519 key. Events expose repository and GitHub numeric IDs, action types and timestamps. New rating values are also public; old values are not retroactively published. New review events expose a salted hash and its salt, allowing anyone to check a visible review; short or predictable hidden text could be guessed from its hash. Review text itself is not included in the journal. Receipts may contain other private salts and should be kept private. This is a service signature, not a user signature. Reports themselves are not public.

Pin the base64 public key through a trusted, separate channel. Merely downloading the key from the service does not establish trust. After activation, periodically run the following on a separate machine with a copy outside the operator's control; until then the mirror is a local preparation, not an independent witness:

```sh
python journal_mirror.py sync https://SERVICE_ORIGIN ./journal.jsonl PINNED_PUBLIC_KEY
python journal_mirror.py verify-receipt ./journal.jsonl PINNED_PUBLIC_KEY ./receipt.json --value-file ./value.json
```

The second command verifies the receipt signature, inclusion in the saved chain and, when supplied, a JSON value against the salted commitment. For a rating use `{"rating": 5}`; for a review use `{"body":"...","security_concern":false,"evidence_url":null}`. The value must match exactly. The mirror detects a conflicting or shortened chain after a previous sync. By itself it does not reconcile database rows, scores or displayed content with the journal, detect selective views, or protect changes made before an independent copy exists. Existing feedback has no signed historical receipts. Back up the journal and receipts separately, and check them regularly; a backup held only by the operator is not independent.

The experimental auditor recomputes the score from published rating events and checks displayed reviews against their signed commitments, fetching account ages and repository identity from GitHub. Run it periodically on a separately administered machine:

```sh
python audit_feedback.py https://SERVICE_ORIGIN OWNER/REPO ./journal.jsonl PINNED_PUBLIC_KEY --accept-unverified-baseline
```

This explicitly opts into a limited check: there is no independently verified complete baseline, so success cannot establish that every historical or hidden entry was included. The auditor stops on legacy events without verification data, a mismatch, API failures or 50 or more visible reviews. Concurrent changes can cause an inconclusive mismatch. A service operator who controls the signing key can fabricate events or show different views; a service signature is not proof of the author's action. An operator-controlled GitHub repository is a backup, not an independent witness.

`.github/workflows/transparency.yml` runs every six hours and on demand. It verifies and copies the signed journal into `audit-history`, signs a checkpoint using GitHub OIDC and Cosign, verifies its Sigstore bundle, and then compares the public feedback with the journal. Rekor stores an independently verifiable signature and hash, not the journal itself. The workflow pins the service public key in the repository variable `FEEDBACK_JOURNAL_PUBLIC_KEY`. Its final comparison flags unsigned reviews and rating discrepancies as warnings; a successful run with warnings does not certify the preexisting baseline or the displayed rating. Changes or omissions of a visible signed review fail the check. The account owner can alter or stop the workflow and delete the GitHub copy; retain checkpoint bundles and mirror files separately to check future rewrites. Scheduled Actions are best effort, not continuous surveillance.

For a separate public test, an operator can set `FEEDBACK_TEST_REPO` to one exact repository name. Only its signed-in GitHub owner may submit at `/test?repo=OWNER/REPO`; requests use the normal Origin, CSRF and rate checks. Test entries are public, permanently signed as `test_rating` and `test_review`, and displayed only in the explicitly marked test card. They never enter the real rating or README card. The workflow checks this card against the signed events; this exercise does not replace a real eligible user's review or prove identity independently of the service.

## Deployment and migration

Back up and verify the dedicated database first. On an existing PostgreSQL installation that already has `transparency_migration.sql`, apply `migrations/002_owner_replies.sql`, `003_seals.sql`, `004_security_concerns.sql` and `005_signed_journal.sql` in that order using a database administrator connection, before starting the updated application. Review each migration and execute it once. On a fresh database, use the current `postgres_schema.sql` instead; do not also apply the same migrations. Confirm required roles and grants exist. Never put credentials in files committed to Git.

In Render configure `FEEDBACK_BASE_URL` as the exact HTTPS origin, `FEEDBACK_COOKIE_SECURE=true`, the dedicated `DATABASE_URL`, `FEEDBACK_JOURNAL_PRIVATE_KEY`, and `FEEDBACK_MODERATOR_IDS` for explicitly appointed operators. The PostgreSQL adapter verifies the server hostname and bundled Supabase CA. Set `FEEDBACK_SEAL_CRON_TOKEN` in Render and the same secret in the GitHub repository Actions secrets; enable `.github/workflows/seal-check.yml` in an independently operated repository if removal monitoring is to be independent of the reviewed repository owner. Its configured URL must point to the deployed service. Start with `gunicorn --workers 1 --bind 0.0.0.0:$PORT 'app:create_app()'`.

Before release, test OAuth administrator permissions against GitHub, verify the scheduler actually runs, save and verify receipts against a separately retained journal, and test backup restoration. Export format 2 contains private reports and other sensitive records; keep backups private. The backup table set changed with these migrations, so older format-2 exports need a separate compatibility procedure before restore. Render's default filesystem is ephemeral; SQLite there requires persistent storage. Production still needs monitoring, an appeal process, request limiting at deployment level and independent oversight.
