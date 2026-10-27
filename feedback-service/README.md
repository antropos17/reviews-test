# Community feedback service

A local implementation of a shared feedback service for public GitHub repositories. Ratings and written reviews are independent. This implementation has not yet been qualified for public production use.

## Local setup

Requires Python 3.10 or later. Install `requirements.txt` into a virtual environment. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` using your shell or secret manager; never commit them. Configure a GitHub OAuth app callback as `http://127.0.0.1:8766/auth/callback`, then start `python app.py` and open `http://127.0.0.1:8766/?repo=OWNER/REPO`.

Without OAuth credentials, public repository lookup is available but sign-in is disabled. The local database is `feedback.sqlite3`, which is ignored by Git.

Run checks with `python -m unittest discover -s tests -v`. The tests mock GitHub's API and do not establish that a real GitHub sign-in works.

## Rules and boundaries

- One current rating and one current review per GitHub user ID and repository ID. Rating changes do not overwrite reviews and vice versa. Repository owner accounts cannot submit ratings or reviews to their own repository, and their existing ratings are excluded; historical owner reviews remain visible and are labelled.
- Only GitHub users are accepted; accounts younger than 30 days are held until eligible, without an owner approval override. The average is the arithmetic mean of eligible ratings. The service operator can still modify service code and data.
- GitHub sign-in uses state and PKCE; session cookies are HttpOnly and SameSite=Lax. Authenticated writes require the exact configured Origin and a session CSRF token. GitHub access tokens are used only to retrieve the user profile and are not persisted by this application.
- Successful changes are limited per account and per entry. Reports require a 30-day-old account, are limited to ten per account per hour and one per reviewer/review version, and do not hide content automatically. Multiple old GitHub accounts belonging to one person and organization member conflicts are not reliably distinguishable.
- Repository IDs are resolved using GitHub's API. GitHub outages or API limits can prevent reads and writes. Current public API verification does not support renamed-repository redirects.
- Reviews render as plain text. Reports are private to designated moderators; their decisions appear in the public log. Configure `FEEDBACK_MODERATOR_IDS` as comma-separated numeric GitHub user IDs. No moderator is configured by default, and the repository owner cannot moderate that repository. Review revisions bind decisions to the reported content. The public log displays the latest 100 decisions. There is no independent appeal channel yet.
- The application role cannot update or delete reports and moderation events, but a database administrator or service operator can alter database privileges, records, code, and moderator configuration. The log is not independently tamper-proof. Do not claim independent governance or guarantee fraud prevention.

## Deployment considerations

Set `FEEDBACK_BASE_URL` to the exact HTTPS origin, `FEEDBACK_COOKIE_SECURE=true`, and `DATABASE_URL` to the dedicated PostgreSQL connection. The supplied PostgreSQL adapter verifies the server hostname and the bundled Supabase CA. Deployments must provision the private schema and restricted application role separately; apply `transparency_migration.sql` once to existing PostgreSQL databases. Never commit credentials. `gunicorn --workers 1 --bind 0.0.0.0:$PORT 'app:create_app()'` starts the service. SQLite requires a persistent filesystem and single-instance operation; backups must use SQLite's online backup mechanism. Render's default filesystem is ephemeral. Export format 2 includes private reports and moderation events; store backups privately. Public production use still requires deployment-level request limiting, an appeal process, operational monitoring, independent oversight, and tested recurring backup and recovery.
