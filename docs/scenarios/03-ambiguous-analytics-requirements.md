# Scenario 3 — Ambiguous: analytics requirements

**Type:** Ambiguous requirement (the brief names a feature, not a spec)

## Requirement

> Build a URL shortener service from scratch with core APIs, **analytics**, and
> reliability features.

That's the entire spec for analytics: one word. It says nothing about which metrics,
what time granularity, whether raw events are needed vs. aggregates only, what happens to
analytics for a deleted link, or how (or whether) to handle personally identifiable
information like IP addresses. Rather than pick something arbitrarily and move on, the
ambiguity itself is treated as the first thing to resolve.

## Decomposition of the ambiguity

Five concrete questions had to be answered before any code made sense to write:

1. **Raw events or aggregates-only?** A pure counter (Scenario 1/2's `click_count`)
   can't answer "when" or "from where." A dashboard-shaped feature needs event-level data
   to aggregate from.
2. **What dimensions matter?** Time (when clicks happened) and source (referrer) are the
   two that generalize across almost any link-sharing use case, without needing to guess
   at a specific business's KPIs.
3. **Does this need to identify individual visitors?** There's no auth in this system
   (an explicit prior scope cut — see `docs/TESTING.md`), so there's no concept of "a
   user" to attribute a click to. But even anonymous visitor data (IP addresses) is
   personal data in most privacy regimes.
4. **What happens to analytics when a link is soft-deleted?** Scenario 2 made soft delete
   preserve the row specifically so this question would have an answer already implied by
   an earlier decision.
5. **What's "recent enough" to report?** No SLA or dashboard mockup exists to derive this
   from, so a judgment call was needed on retention/granularity.

## Assumptions made (and why)

| Question | Assumption made | Why |
|---|---|---|
| Raw events vs. aggregate-only | Store a `ClickEvent` row per click (`app/models.py`), keep the existing `ShortUrl.click_count` as a fast denormalized total | Aggregates can always be computed from events; the reverse isn't true. Storing events is the option that doesn't foreclose future questions the requirement didn't ask (e.g. "clicks by hour" later) |
| Dimensions | Time-series (last 7 days, day granularity) + top 5 referrers + a 24h rolling count | Covers "is this link getting traction" and "where is traffic coming from" — the two questions almost any link-sharing use case actually has, without inventing business-specific KPIs nobody asked for |
| Visitor identification | Never store a raw IP. Hash it (`app/privacy.py::hash_ip`, unsalted SHA-256, truncated) before persisting, and don't expose it via any API at all — it currently exists only as a column, unused by the analytics endpoint | With no auth and no consent flow in this prototype, the safer default is to not collect PII rather than collect it and hope a future feature needs it. This is called out explicitly, not left implicit: the field is unsalted, which is a real trade-off (documented in `app/privacy.py`'s own docstring), not a strong anonymization claim |
| Deleted-link analytics | Still queryable after soft delete (validated by `test_analytics_survives_soft_delete`) | Falls directly out of Scenario 2's soft-delete decision — a link being retired shouldn't erase what it did while live |
| Retention/granularity | 7-day daily time series, 24h rolling count, top 5 referrers, unlimited event retention (no purge job) | Small enough to be genuinely useful without a spec to size it against; unlimited retention is flagged as a limitation, not silently shipped as if it were a considered production decision |

## Execution

- `app/models.py` gains `ClickEvent` (`short_url_id` FK, `clicked_at`, `referrer`,
  `user_agent`, `ip_hash`) — deliberately separate from `ShortUrl`, so a fast metadata read
  never has to scan the event table.
- `app/routes/redirect.py` captures `referer`/`user-agent` headers and the hashed client IP
  *while the request is live*, then hands them to a `BackgroundTask`
  (`crud.record_click_background`) so, as with Scenario 2's click counter, analytics
  writes never add latency to the redirect response.
- `crud.record_click` inserts the `ClickEvent` and increments `ShortUrl.click_count` in one
  commit, so the fast counter and the detailed log can never drift apart.
- `crud.get_analytics` computes the 24h count, the 7-day daily series (zero-filled for
  quiet days, so a caller doesn't have to do that bookkeeping), and the top-5 referrers,
  grouping `None` referrers as `"direct"` traffic.
- New endpoint: `GET /api/urls/{code}/analytics` (`app/routes/analytics.py`).
- **A real latent bug found while doing this work, unrelated to analytics itself**:
  `ShortUrl.code` was `String(16)`, but Scenario 2's custom-alias validation allows up to
  30 characters. SQLite doesn't enforce column length, so every test still passed and
  nothing broke — but the column wouldn't have matched validation on Postgres. Widened to
  `String(32)` and noted in `app/models.py`, because "the tests passed" isn't the same
  claim as "the code is correct."

## Validation

- **Unit** (`tests/unit/test_crud.py`): analytics aggregation tested directly against a
  seeded set of `ClickEvent` rows — multiple referrers ranked correctly, `None` referrer
  reported as `"direct"`, a zero-click link returns an all-zero (not missing/error)
  response, and `record_click_background` exercised end-to-end including a call to
  `get_analytics` afterward to confirm the two code paths (write, then read) agree.
- **API** (`tests/api/test_analytics_api.py`): `404` for an unknown code, all-zero
  analytics for a freshly created link, a real click via the live server reflected in
  `total_clicks`/`clicks_last_24h`/`top_referrers` (polled briefly, since the write is
  backgrounded — same pattern as Scenario 2), and analytics remaining readable after the
  link is soft-deleted.
- **E2E** (`tests/e2e/test_ui_flow.py::test_analytics_link_leads_to_analytics_json`): the
  browser follows the UI's new "View analytics" link and confirms the JSON response
  actually renders, proving the new endpoint is wired into the UI, not just reachable by
  curl.

Result at the end of this scenario: 26 unit tests, 24 API tests, 3 E2E tests, all passing.
