# Trust product direction

## Positioning and competitive evidence (2026-11-03)

This is not an empty market. The following primary sources establish existing capabilities, not market share or commercial demand:

| Product | Existing capability | Useful pattern for Community Feedback |
| --- | --- | --- |
| [G2](https://documentation.g2.com/help/docs/how-g2-ensures-authentic-reviews) | Manual moderation, sign-in, experience evidence and conflict-of-interest checks; AI assistance allowed under conditions | Separate account identity, experience evidence and conflict-of-interest labels. Our intended policy disallows generated review text. |
| [Trustpilot](https://help.trustpilot.com/s/article/How-do-reviews-get-on-Trustpilot?language=en_US) | Reviews can receive a verified experience label after evidence is supplied | Award experience labels only after evidence review; sign-in alone must not receive that label. |
| [OpenSSF Scorecard](https://openssf.org/projects/scorecard/) | Automated repository security-practice checks and individual risk signals | Link evidence, preserve check-level results and distinguish practices from malware analysis. |
| [Socket](https://docs.socket.dev/docs/faq) | Dependency behavior and supply-chain risk analysis | Treat suspicious behavior, known malware and vulnerabilities as separate findings. |
| [Snyk](https://updates.snyk.io/snyk-advisor-insights-are-now-part-of-security-snyk-io/) | Vulnerability information combined with package-health insights | Keep package/release identity and maintenance signals visible separately. |
| [SafeDep vet](https://github.com/safedep/vet) | Open-source dependency vetting and malicious-package intelligence queries | Prefer attributable evidence and exact dependency versions over a universal safe/unsafe score. |

Inference: a generic "VirusTotal for GitHub" pitch overlaps established tools. A more distinct product combines first-hand project reviews, transparent independent moderation and separately attributed technical evidence. This research does not establish market saturation, willingness to pay, global trust or a defensible business.

## Implemented in the local revision

- Directory: eligible community score, fractional stars, rating count, public review count, bounded latest public excerpt, top/most-reviewed/recent sorting. Top requires five eligible ratings; service test repositories are excluded. Score is arithmetic, with sample size visible.
- Existing owner exclusion, age threshold and hidden-review rules also apply to directory scores. Unknown ownership withholds the rating. Database failure is unavailable, never a fabricated zero or perfect score. Catalog reads do not insert repositories or feedback.
- New reviews and edits require an explicit first-hand, no-generated-text/no-agent declaration on the server. The signed event records the declaration, without rewriting old events or old reviews. This is not authorship verification.
- Optional Turnstile: provider verification before rating/review/reply/report writes, action and hostname checks, five-minute freshness, provider-side single-use validation, bounded timeouts and no automatic write retries. Partial configuration is rejected. Disabled until real keys are configured. No CAPTCHA solving or production challenge test was performed.
- A consistent existing Community Feedback mark and horizontal badge identify the service. Security remains "not independently assessed"; project pages link OpenSSF Scorecard and repository advisories. No imported scanner results or malware-free badge is claimed.

## Remaining product work and acceptance

1. **Authenticity and moderation:** establish independent operators, private experience-evidence intake, a moderation queue for suspected manipulation, impartial reason codes and an appeal/contact channel. Define retention and least-privilege access before collecting screenshots. A CAPTCHA, account age and declaration do not identify a unique human or exclude all agents. Do not deploy unreliable AI-writing detectors as proof.
2. **Activate the CAPTCHA:** create a Turnstile widget restricted to the exact production hostname; configure the site and secret keys privately; validate successful submission, expired/replayed token rejection, provider outage and accessible recovery with a real non-owner account. No new account, credentials, external settings or production write is created by this revision.
3. **Security evidence:** select one bounded source integration before building another scanner. Every result needs provider, repository ID, exact commit or artifact digest, scan time, tool version, scope, check results and freshness. Distinguish unknown, stale, incomplete, suspicious and confirmed malicious. Evidence must be appealable. Do not execute arbitrary repository code or upload private sources as part of browsing.

## Badge contract

Keep the same mark, service name, score/count and link across projects. Never sell a higher rating. Keep community feedback separate from security, experience verification and journal integrity. Reserve labels such as "experience verified" or "security assessed" for completed, documented checks, linked to a public methodology and dated evidence. Global recognition is an adoption outcome, not a certification we can award ourselves.

## Scope

No database schema migration, production data mutation, deployment, new automation, external account creation or new paid service is required for this local revision. Existing reviews and backups remain intact. Real non-owner acceptance is still unavailable without another eligible GitHub account.
