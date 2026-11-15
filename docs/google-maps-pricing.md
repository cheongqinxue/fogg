# Google Maps Platform pricing reference

**Checked:** 2026-11-14
**Scope:** Google Maps APIs currently called by FOGG's `gmaps` client.
**Price basis:** Global price list, USD per 1,000 billable events. The account's
billing country, currency, contract, and monthly volume can change the actual
rate. Confirm the project-specific rate in Google Cloud Billing before
budgeting.

## How to read these prices

Google prices each API by SKU. Monthly free usage caps and paid rates are
tracked per SKU. The price bands below are progressive monthly volume bands:
each rate applies only to events in that band. A free cap of 5,000, for
example, means events 1–5,000 are free; the first paid rate applies from event
5,001 through 100,000.

For Places Text Search, Nearby Search, and Place Details, the field mask sets
the request's SKU: if fields span multiple tiers, the whole request uses the
highest applicable tier. More fields within one tier do not create separate
per-field charges. `*` can include fields in the highest tier, so use it for
inspection only. [Google's Places SKU rules](https://developers.google.com/maps/billing-and-pricing/sku-details/places)
and [field-mask guidance](https://developers.google.com/maps/documentation/places/web-service/choose-fields)
describe these rules.

Routes pricing is based on route features rather than response size. Compute
Routes bills per request; Compute Route Matrix bills per origin-destination
element (`origin_count × destination_count`). Traffic-aware routing and other
advanced features can change the SKU. [Routes usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
has the current triggers and limits.

## APIs used by FOGG

| API operation | Billable event | What changes the SKU / billing behavior |
|---|---|---|
| Places Text Search (New) | One successful request | Highest Places field tier in the mask. ID-only field masks have an unlimited free cap. |
| Places Nearby Search (New) | One successful request | Highest Places field tier in the mask. Nearby Search has no separate IDs-only SKU; `places.id` is in its Pro SKU. |
| Place Details (New) | One successful request | Highest Places field tier in the mask. ID-only fields have an unlimited free cap. |
| Places Autocomplete (New) | One request, or session-priced usage | The examples omit a session token, so each request uses the Autocomplete Requests SKU. Proper session tokens and a qualifying Place Details follow-up can change session billing. |
| Routes Compute Routes | One successful request | Billed by route feature tier, not number of returned fields. More than 10 intermediate waypoints, waypoint optimization, and traffic-aware routing can raise the tier. |
| Routes Compute Route Matrix | Each returned origin-destination element | Billed by route feature tier for every element. A 1-origin × 2-destination request is 2 elements. |

## Global price bands

All prices are **USD per 1,000 events**. The free cap and each paid band apply
separately to each SKU per month. `Unlimited` means the listed SKU has no
charge in Google's current global price list.

### Places API (New)

| SKU | Monthly free cap | First paid band through 100k | 100,001–500k | 500,001–1m | 1,000,001–5m | Over 5m |
|---|---:|---:|---:|---:|---:|---:|
| Autocomplete Requests | 10,000 | $2.83 | $2.27 | $1.70 | $0.85 | $0.21 |
| Place Details Essentials (IDs Only) | Unlimited | — | — | — | — | — |
| Text Search Essentials (IDs Only) | Unlimited | — | — | — | — | — |
| Place Details Essentials | 10,000 | $5.00 | $4.00 | $3.00 | $1.50 | $0.38 |
| Nearby Search Pro | 5,000 | $32.00 | $25.60 | $19.20 | $9.60 | $2.40 |
| Text Search Pro | 5,000 | $32.00 | $25.60 | $19.20 | $9.60 | $2.40 |
| Place Details Pro | 5,000 | $17.00 | $13.60 | $10.20 | $5.10 | $1.28 |
| Nearby Search Enterprise | 1,000 | $35.00 | $28.00 | $21.00 | $10.50 | $2.63 |
| Text Search Enterprise | 1,000 | $35.00 | $28.00 | $21.00 | $10.50 | $2.63 |
| Place Details Enterprise | 1,000 | $20.00 | $16.00 | $12.00 | $6.00 | $1.51 |
| Nearby Search Enterprise + Atmosphere | 1,000 | $40.00 | $32.00 | $24.00 | $12.00 | $3.40 |
| Text Search Enterprise + Atmosphere | 1,000 | $40.00 | $32.00 | $24.00 | $12.00 | $3.40 |
| Place Details Enterprise + Atmosphere | 1,000 | $25.00 | $20.00 | $15.00 | $7.50 | $2.28 |

### Routes API

| SKU | Monthly free cap | First paid band through 100k | 100,001–500k | 500,001–1m | 1,000,001–5m | Over 5m |
|---|---:|---:|---:|---:|---:|---:|
| Compute Routes Essentials | 10,000 requests | $5.00 | $4.00 | $3.00 | $1.50 | $0.38 |
| Compute Route Matrix Essentials | 10,000 elements | $5.00 | $4.00 | $3.00 | $1.50 | $0.38 |
| Compute Routes Pro | 5,000 requests | $10.00 | $8.00 | $6.00 | $3.00 | $0.75 |
| Compute Route Matrix Pro | 5,000 elements | $10.00 | $8.00 | $6.00 | $3.00 | $0.75 |
| Compute Routes Enterprise | 1,000 requests | $15.00 | $12.00 | $9.00 | $4.50 | $1.14 |
| Compute Route Matrix Enterprise | 1,000 elements | $15.00 | $12.00 | $9.00 | $4.50 | $1.14 |

## What the current examples cost by design

The scripts under `agent/src/gmaps/_examples/` use wildcard field masks to
show full response shapes. This can put Text Search, Nearby Search, and Place
Details into their highest applicable Places tier. Their page/result limits
still limit the amount of data returned, but do not lower a field-mask SKU.
The examples disable the Redis response cache and local quota tracking; Google
still bills successful live requests.

The Route Matrix example uses one origin and two destinations, so a successful
call returns two billable elements. It uses walking mode without traffic-aware
options, so the route feature tier is expected to be Essentials. The wildcard
mask is for inspecting the response and does not itself select the Routes Pro
or Enterprise feature tiers.

## FOGG quota-estimator caveat

FOGG's local quota tracker is an estimate for our configured free-tier caps;
it is not Google's invoice. It classifies supported request options, including
two-wheeled routing, conservatively. Any newly added billing feature must first
be reflected in SKU classification. Google aggregates monthly free usage for
all projects linked to the billing account, while this tracker sees this
client's requests only. See [`google-maps-quota-safety.md`](google-maps-quota-safety.md)
for hard-stop and reconciliation guidance.

## Official sources

- [Google Maps Platform global pricing list](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Places (New) SKU details](https://developers.google.com/maps/billing-and-pricing/sku-details/places)
- [Google Maps Platform SKU details](https://developers.google.com/maps/billing-and-pricing/sku-details)
- [Places field masks](https://developers.google.com/maps/documentation/places/web-service/choose-fields)
- [Routes usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)

**Maintenance:** Pricing changes. Recheck the official pricing list and SKU
triggers before relying on this document for a budget or launch decision.
