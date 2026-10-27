# Community feedback service

A local implementation of a shared feedback service for public GitHub repositories. Ratings and written reviews are independent. This implementation has not yet been qualified for public production use.

## Local setup

Requires Python 3.10 or later. Install `requirements.txt` into a virtual environment. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` using your shell or secret manager; never commit them. Configure a GitHub OAuth app callback as `http://127.0.0.1:8766/auth/callback`, then start `python app.py` and open `http://127.0.0.1:8766/?repo=OWNER/REPO`.

Without OAuth credentials, public repository lookup is available but sign-in is disabled. The local database is `feedback.sqlite3`, which is ignored by Git.

Run checks with `python -m unittest discover -s tests -v`. The tests mock GitHub's API and do not establish that a real GitHub sign-in works.

## Rules and boundaries

- One current rating and one current review per GitHub user ID and repository ID. Rating changes do not overwrite reviews and vice versa.
- Only GitHub users are accepted; accounts younger than 30 days are held until eligible, without an owner approval override. The average is the arithmetic mean of eligible ratings. The service operator can still modify service code and data.
- GitHub sign-in uses state and PKCE; session cookies are HttpOnly and SameSite=Lax. Authenticated writes require the exact configured Origin and a session CSRF token. GitHub access tokens are used only to retrieve the user profile and are not persisted by this application.
- Successful changes are limited per account and per entry. Multiple old GitHub accounts belonging to one person are not distinguishable. The operator should add abuse handling, deployment-level request limiting, monitoring and a privacy policy before public launch.
- Repository IDs are resolved using GitHub's API. GitHub outages or API limits can prevent reads and writes. Current public API verification does not support renamed-repository redirects.
- Reviews render as plain text. The current implementation has no reporting, deletion, or moderation UI and no independent audit or appeal process.

## Deployment considerations

Set `FEEDBACK_BASE_URL` to the exact HTTPS origin, `FEEDBACK_COOKIE_SECURE=true`, and `DATABASE_URL` to the dedicated PostgreSQL connection. The supplied PostgreSQL adapter verifies the server hostname and the bundled Supabase CA. Deployments must provision the private schema and restricted application role separately; never commit database credentials. `gunicorn --workers 1 --bind 0.0.0.0:$PORT 'app:create_app()'` starts the service. SQLite requires a persistent filesystem and single-instance operation; backups must use SQLite's online backup mechanism. Render's default filesystem is ephemeral. Public production use still requires live OAuth and end-to-end verification, operational abuse handling, and a tested recurring backup and recovery process.
