# Google Maps quota safety and billing reconciliation

**Reviewed:** 2026-11-14. **No live Google Maps requests are needed** to use or
verify these controls.

## What local enforcement guarantees

When `GMAPS_QUOTA_ENFORCE=true` and Redis is available, every uncached request reserves its estimated
SKU units in Redis before HTTP is sent. A request that would exceed the
configured monthly free cap is blocked before reaching Google. Reservations
are atomic across workers sharing the same Redis instance. Matrix reservations
count origin-destination elements. Requests whose outcome is ambiguous (for
example, a read timeout) remain counted because Google may have received them;
only failures known to happen before send are refunded. Retries reserve each
attempt.

SKU selection is deliberately conservative: unknown Places fields and wildcard
masks map to the highest supported tier, and unknown internal SKUs are rejected
before a request. Routes Two-Wheeler mode maps to Enterprise. These rules must
be updated when request features or Google's SKU triggers change. See
[`google-maps-pricing.md`](google-maps-pricing.md).

This is a **local guardrail, not an absolute no-charge guarantee**. Google
aggregates monthly SKU usage across every project linked to a billing account.
Our Redis counter sees only calls through this client, so another project can
consume the free allowance first. It also cannot account for other callers on
this project, Google-side classification changes, loss of recent Redis writes,
or inaccurate SKU assumptions. For the strongest no-charge setup, use a
dedicated billing account with no other Maps usage, a dedicated project/key,
and both local enforcement and Google daily quotas. Redis connection and timeout
errors allow the API request through and log a warning. Usage during an outage
may be missing from the counters, so local enforcement can remain inaccurate
after Redis recovers. Google billing and service behavior are authoritative.

## Add a Google-side hard stop

Set per-API daily quotas in Google Cloud Console as an independent breaker.
Google says daily quotas reset at midnight Pacific Time. For a conservative
monthly free-tier ceiling, choose the **lowest free cap among SKUs that API can
trigger** and set its daily quota no higher than `floor(monthly free cap / 31)`;
use the SKU's billable unit. For example, 10,000 units gives 322/day; 5,000
gives 161; 1,000 gives 32.
For Compute Route Matrix, the quota must be measured in elements, not API
requests. A request with 20 elements consumes 20 units. This daily setting can
stop service for the rest of the day and must account for any other clients
sharing that project. It is a hard per-project API quota, but it does **not**
reserve the billing account's free allowance for this project. Google
documents daily quota controls in
[Manage costs](https://developers.google.com/maps/billing-and-pricing/manage-costs).

Google's monthly free-use thresholds and the monthly local counter are not a
substitute for this daily project quota: Google billing can aggregate usage at
a broader billing-account scope, while this Redis counter only sees this
service's traffic.

## Compare local use with billing the next day

Daily counters are stored alongside the monthly counters in the same Redis
transaction. They use Google's Pacific billing day. Export a local snapshot
for the prior day (in the agent environment, with Redis available):

```bash
uv run --project agent python -m gmaps.quota.report --day YYYY-MM-DD
```

Enable **Cloud Billing standard usage cost export** to BigQuery for the billing
account. Billing export is delayed and has no delivery-time guarantee, so check
the prior day's usage after it appears; a discrepancy is detection, not a
real-time blocker. Do not interpret cost alone as request count: compare SKU,
usage amount, usage unit, project, and Pacific usage date. Exclude credits when
comparing raw usage. Google documents the export schema and its latency caveat
in [Export Cloud Billing data to BigQuery](https://cloud.google.com/billing/docs/how-to/export-data-bigquery)
and [standard usage cost data](https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage).

Example query for the standard export table (replace the table identifier and
project ID):

```sql
SELECT
  DATE(usage_start_time, "America/Los_Angeles") AS pacific_day,
  project.id AS project_id,
  sku.description AS sku,
  usage.unit AS usage_unit,
  SUM(usage.amount) AS usage_amount,
  SUM(cost) AS gross_cost
FROM `BILLING_PROJECT.BILLING_DATASET.gcp_billing_export_v1_BILLING_ACCOUNT_ID`
WHERE service.description = "Google Maps Platform"
  AND project.id = "YOUR_MAPS_PROJECT_ID"
  AND DATE(usage_start_time, "America/Los_Angeles") = DATE_SUB(
    CURRENT_DATE("America/Los_Angeles"), INTERVAL 1 DAY
  )
GROUP BY pacific_day, project_id, sku, usage_unit
ORDER BY sku;
```

SKU labels in billing may not match internal names one-to-one. Maintain a
reviewed mapping from each billing SKU description and unit to the internal
SKU in `gmaps/requests/sku.py`; investigate any billing row without a mapping
and any material local-vs-billing count difference. BigQuery storage and query
usage can themselves incur charges; apply the project's normal controls.

## Operational checks

- Keep `GMAPS_QUOTA_TRACKING=true` and `GMAPS_QUOTA_ENFORCE=true` in production.
- Use Redis persistence and backups appropriate for quota state. AOF
  `appendfsync everysec` can lose recent writes on abrupt failure; after Redis
  data loss, pause Maps traffic until counters are reconciled or reset from
  billing data.
- Review the prior Pacific day after billing export arrives and investigate
  mismatches before continuing if local usage appears understated.
- Review monthly usage in Google Cloud Billing; local enforcement cannot
  observe calls made elsewhere on the billing account.
- Never use wildcard Places masks in production unless the highest tier is
  intended and budgeted.
