# Multi-tenant identity and provider-key security plan

**Status:** proposed implementation plan
**Scope:** tenant isolation, transport and at-rest encryption of customer provider keys, and request-time authentication/decryption
**Pricing checked:** 2026-11-19 (USD; provider prices and free tiers can change)

## Goal

Allow an authenticated customer to save a search-provider API key for their FOGG workspace. FOGG stores only ciphertext, associates it with the correct tenant, and decrypts it only when an authorized request needs to call that provider.

The API key is a credential for an external provider. It is not a key that the customer uses to encrypt FOGG data. FOGG will initially protect customer credentials with a FOGG-managed cloud KMS key.

### The short version

| Technical idea | In everyday terms |
|---|---|
| A tenant is a customer workspace. | A workspace is a locked folder shared by its members. |
| The browser authenticates a user; the API authorizes workspace access. | Signing in proves who you are; FOGG separately checks which workspace you may use. |
| FOGG stores an encrypted provider key and decrypts it for one authorized call. | FOGG keeps the key in a locked box and opens it only when it needs to make the search request. |
| KMS protects and controls use of the encryption key. | KMS is the guarded key cabinet; it unlocks the box for the service, not for the customer. |
| TLS protects data while it travels between systems. | TLS is the sealed, authenticated pipe between the browser, FOGG, KMS, and the provider. |

The main trust boundary is FOGG itself: while making a provider request, the service must briefly have the customer's API key in memory. Encryption protects stored data and network traffic, but it cannot make the service use a secret without seeing it. The design therefore limits who can cause a decrypt and how long the plaintext is kept.

## In scope

- Establish an authenticated user identity and bind it to a tenant/workspace.
- Store and enforce tenant membership for the credential-management and agent-request paths.
- Upload, replace, inspect status for, and delete a tenant's provider key.
- Protect the key in transit and at rest.
- Resolve and decrypt a tenant's key just in time for an authorized provider request.
- Keep all cloud identity and KMS services mocked in local development until we choose to pay for managed services.
- Estimate the incremental identity and KMS costs for a minimal deployment.

## Out of scope

- Billing, subscriptions, provider-usage metering, or quota enforcement.
- Search-provider selection, search-result quality, provider terms, or result caching.
- Customer-managed encryption keys, per-customer KMS keys, HSMs, or confidential computing.
- A general authorization/roles product. Only the minimum workspace membership and key-management permission needed here is included.
- Broader user profile, social login, password-recovery, enterprise SSO, or MFA product design. A managed identity provider should own these mechanisms.

## Decisions to confirm before production

1. **Tenant meaning:** treat a tenant as a customer workspace/account. A workspace owns one key per provider; members use that key when acting within that workspace.
2. **Identity provider:** use a standards-based managed identity provider rather than writing password storage and an authorization server ourselves. AWS Cognito and Supabase Auth are costed below; no provider is selected by this plan.
3. **KMS provider:** local work uses a mock KMS adapter. Production uses one symmetric KMS key shared across tenant credentials, with tenant/provider context bound to each ciphertext. No per-tenant KMS key at launch.
4. **Authentication transport:** use HTTPS and an OIDC/OAuth authorization-code flow with PKCE for the browser. The API validates access tokens; the browser never decides its own tenant authority.
5. **Plaintext lifetime:** do not retain decrypted keys between requests or calls in the first implementation. Decrypt immediately before the provider request, then release references after the request.

## Identity and tenant model

**In plain language:** the identity provider tells FOGG which person signed in. FOGG's membership records then decide which workspace that person can act for. A user ID or workspace ID supplied by the browser is only a request; it is never proof of permission.

### Identities

The identity provider authenticates a person and issues an access token. FOGG's FastAPI service acts as the resource server. It validates the token signature, issuer, audience, expiry, and required scope before constructing a trusted request principal.

For the Svelte browser app, use Authorization Code with PKCE. Public browser clients must use PKCE under current OAuth security guidance ([RFC 7636](https://www.rfc-editor.org/rfc/rfc7636), [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)). Validate JWT access tokens as access tokens, not as ID tokens; at minimum check signature, issuer, audience, expiry, and token type/claims. Use the identity provider's published key set and handle key rotation.

Do not treat `/v1/users/{user_id}` or a client-supplied `tenant_id` as proof of identity or workspace membership. The authenticated subject must be resolved to an internal user and authorized tenant membership. Existing user-scoped chat routes must reject a path user that does not match the authenticated principal or remove that redundant authority from the route contract.

### Minimum tenant records

Add or define these concepts in Postgres:

- `tenants`: internal UUID, display name, created timestamp.
- `identity_accounts`: identity provider issuer plus stable subject, mapped to an internal user UUID. Do not use email as the permanent identity key.
- `tenant_memberships`: tenant UUID, internal user UUID, minimal role, created timestamp. Initially only `owner`/`admin` can manage provider keys; other members may use a configured key if the product permits them to act in that workspace.
- `tenant_provider_credentials`: tenant UUID, provider name, ciphertext, encryption-key identifier/version, encrypted-at timestamp, and credential version. Unique constraint on `(tenant_id, provider)`.

Avoid storing the plaintext key, a reversible copy outside the ciphertext column, or a loggable prefix/suffix. The UI only needs a `configured` state and update/delete actions; do not return the key after upload.

### Enforce tenant boundaries

Resolve tenant membership once from the validated principal and the requested workspace. Pass an immutable trusted `TenantContext` through the request/agent execution. Never derive it from model arguments, graph state supplied by the client, Redis keys, or an unvalidated thread ID.

Credential reads, writes, and deletes must always include the authorized tenant UUID in the repository query. Add Postgres row-level security to the new tenant and credential tables as a second boundary, with tenant context set transaction-locally only after API authorization. Keep connection-pool reuse inside a transaction boundary so a prior request's tenant setting cannot leak to another request.

The same tenant identity must scope the agent's conversation/checkpoint lookup before a graph is resumed. A valid user token must not make another tenant's thread or provider key addressable.

## Encryption design

**In plain language:** HTTPS protects the key as it moves. KMS-backed encryption protects it in the database. When the agent needs a provider, FOGG checks workspace access, opens the encrypted key for that call, and sends it to the provider over HTTPS. KMS performs the encrypt/decrypt operation for the authenticated FOGG service; it does not return a master key to the browser.

### In transit

- Browser to FOGG API: HTTPS only, TLS 1.3 preferred and TLS 1.2 minimum; disable obsolete TLS versions and redirect/reject plaintext HTTP at the edge. OWASP recommends TLS 1.3 by default and TLS 1.2 only for compatibility ([OWASP TLS Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html)).
- FOGG API to identity provider and KMS: provider SDK over verified HTTPS/TLS using workload identity. Do not put cloud credentials in `.env`, Docker `ARG`, or committed configuration.
- FOGG to search provider: HTTPS. The provider key is sent only in the provider's required authorization header or request field.
- Do not add custom browser-side encryption on top of TLS. FOGG must recover the key to make the provider request, so client-side encryption would not remove FOGG from the trust boundary.

TLS does not cost an extra fee as a protocol. A hosting provider, load balancer, or certificate service may charge for the infrastructure around it, but certificates from common automated certificate authorities can be free. TLS also does not protect a key after it reaches the authorized FOGG process; access control, redaction, and short plaintext lifetime still matter.

### At rest

For launch, provider API keys are small enough for direct symmetric KMS encryption. AWS KMS documents `Encrypt` for up to 4,096 bytes and supports an encryption context that must match on decrypt; those context values are non-secret and may appear in CloudTrail ([AWS KMS Encrypt](https://docs.aws.amazon.com/kms/latest/APIReference/API_Encrypt.html)). Enforce a small maximum key size and reject larger values.

For each credential write:

1. Build encryption context from immutable values: `tenant_id`, `provider`, and `credential_version`. Never put the API key, email, or other sensitive information in this context.
2. Call KMS `Encrypt` with a symmetric key and that context.
3. Store the returned ciphertext and KMS key identifier/version. Do not write plaintext to Postgres, Redis, checkpoints, or debug logs.

For each credential use, call KMS `Decrypt` with the stored ciphertext and the exact same context reconstructed from the authorized database row. A mismatched tenant, provider, or credential version must fail to decrypt. This binds ciphertext to its owner and purpose, preventing a database row from being copied to another tenant and still working.

If any credential later exceeds KMS's direct-encryption size limit, move that provider to envelope encryption: locally encrypt with a fresh data-encryption key and ask KMS to wrap that data key. Do not invent an encryption format; use the cloud SDK or a maintained encryption library.

For local development, implement the same encrypt/decrypt interface with AES-256-GCM and a random 96-bit nonce, authenticating `tenant_id`, `provider`, and `credential_version` as associated data. AES-GCM is specified by NIST SP 800-38D as authenticated encryption with associated data ([NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final)). The development wrapping key belongs only in an ignored local `.env`; it must be generated randomly and must never be reused in production. Unit tests use fixed test-only keys and never call cloud KMS.

## Just-in-time authentication and decryption flow

1. User signs in through the configured OIDC identity provider. The browser receives/uses an access token through the chosen secure browser-session design.
2. Browser calls the FOGG API over HTTPS. API validates the token and resolves `(issuer, subject)` to a FOGG user.
3. API authorizes the user for the target tenant and creates trusted `TenantContext` for the request. Reject before starting or resuming the graph if membership is absent.
4. When the graph invokes `web_search` or `web_extract`, the adapter receives the trusted tenant context from server-side execution context; the model cannot choose a tenant or credential ID.
5. Credential repository fetches only `(tenant_id, provider)` ciphertext. The KMS adapter decrypts it using the row's tenant/provider/version context.
6. Provider adapter uses the plaintext only to construct that provider request. It does not attach the credential to tool arguments, prompt, tool output, graph state, exception text, or trace attributes.
7. Drop local references when the call finishes. Do not cache plaintext keys in Redis or process-wide singletons. Cache the ciphertext only in Postgres; if future decryption caching is considered, review its threat model and lifetime separately.
8. Return ordinary provider results to the agent. The credential never returns to the UI; UI responses contain only configured status and non-sensitive metadata.

**One request, step by step:** Alice saves a search-provider key in her workspace. FOGG receives it through HTTPS, confirms she can manage that workspace, encrypts it, and stores ciphertext. Later, Alice asks the agent to search. FOGG checks her workspace membership again, loads only that workspace's ciphertext, asks KMS to decrypt it with the matching workspace/provider/version context, calls the search provider, and discards the plaintext reference. If Bob asks for Alice's workspace or the ciphertext is copied into another workspace, authorization or KMS context validation stops the call.

Plaintext exists in process memory while the provider call is being assembled and sent. Python does not guarantee that deleting a variable securely overwrites the memory bytes, so “discard” means minimize lifetime and references, never log or cache it, and rely on process isolation and platform protections—not claim guaranteed memory zeroization.

If authentication, tenant authorization, KMS decrypt, or context validation fails, do not call the external provider. Return a generic internal error to the client and record a redacted security event.

## Credential-management API/UI behavior

Minimum API operations, all authenticated and tenant-authorized:

- `PUT /v1/tenants/{tenant_id}/credentials/{provider}` — replace the provider key; accept it only in the request body over HTTPS, validate size/format where known, encrypt immediately, persist ciphertext, discard plaintext.
- `GET /v1/tenants/{tenant_id}/credentials` — return provider name, configured state, and update timestamp only.
- `DELETE /v1/tenants/{tenant_id}/credentials/{provider}` — delete the current encrypted record and invalidate any in-flight credential lookup for the next call.

The UI sends a key once in a password input, clears the input after success, and displays only “configured” plus last-updated time. Never prefill, echo, or place a key in browser storage, URLs, analytics, error reporting, or client-side logs.

## Local-first build plan

The expensive external dependencies remain mocked while we finish the foundations. The mocks must run through the same tenant authorization and credential interfaces as production; they must not skip those checks.

### Stage 1 — tenant boundary and identity contracts

- Define internal user, tenant, membership, and trusted `TenantContext` types.
- Add tenant and membership migrations plus tenant-scoped repository methods.
- Add an `IdentityProvider`/token-verifier interface and a local test implementation. The local implementation creates test identities/tokens; it is explicitly unavailable in production configuration.
- Add FastAPI authentication and tenant-membership dependencies for credential and chat paths.
- Add row-level security to the new tenant tables and tests for transaction-local tenant scope.
- Add tests proving a user in tenant A cannot read, replace, delete, or use tenant B credentials, threads, or ciphertext.

### Stage 2 — encrypted credential storage without cloud spend

- Define a `CredentialCipher` interface with `encrypt(plaintext, context)` and `decrypt(ciphertext, context)`.
- Implement the local AES-256-GCM cipher with tenant/provider/version as associated data.
- Add the credential table/repository and key-management API/UI operations.
- Test ciphertext tampering, wrong tenant, wrong provider, wrong version, key replacement, deletion, oversize values, and that API responses never include plaintext.
- Keep local key generation separate from the database and provide no production default.

### Stage 3 — just-in-time use through a fake provider

- Implement a request-time credential resolver: trusted tenant context → credential row → decrypt → provider adapter.
- Use a fake KMS and fake provider client in automated tests. Assert that unauthorized calls never reach decryption/provider code.
- Add regression checks that credentials are absent from tool inputs/outputs, LangGraph checkpoints, Redis keys/values, traces, application logs, and exception messages.
- Wire current tool I/O capture to redact sensitive request headers and ensure the key never appears in captured data.
- Keep the plaintext lifetime within one provider invocation; do not add a plaintext-key cache.

### Stage 4 — managed identity and KMS adapter

- Choose an OIDC identity provider and a cloud KMS after reviewing the cost table and deployment location.
- Configure local/staging/production issuers, audiences, callback URLs, KMS key IDs, and workload identity separately.
- Implement the provider SDK adapters behind the interfaces from Stages 1–3. Use workload identity/short-lived cloud credentials, not static cloud secrets in `.env`.
- Test against a non-production identity tenant and KMS key before deploying to production. These tests must not call Google Maps or search-provider APIs.

### Stage 5 — production enablement gates

- Confirm TLS enforcement, token issuer/audience configuration, tenant membership checks, database RLS, and key-size limits.
- Verify a ciphertext copied between tenants/providers fails decryption.
- Verify key replacement and deletion take effect on the next provider call.
- Inspect application logs, tool I/O JSONL, Phoenix traces, Postgres checkpoints, and Redis for credential leakage using a canary test key.
- Enable real user sign-in and real KMS only after these checks pass. Search-provider keys can remain mocked until separately configured.

## Cost estimate

These are incremental identity/KMS estimates, not total SaaS hosting costs. They exclude the existing FOGG API, Postgres/Redis hosting, TLS/domain costs, network egress, audit-log storage, email verification, and SMS/MFA delivery. Prices are USD and may vary by region and change over time.

### Lowest-cost development path

| Component | Monthly incremental cost |
|---|---:|
| Local mock identity provider | $0 |
| Local AES-GCM development cipher | $0 |
| Fake provider and fake KMS in unit tests | $0 |
| **Total** | **$0** |

This is the recommended path for Stages 1–3. It exercises real tenant checks and authenticated encryption without creating cloud resources or entering provider API keys.

### AWS reference estimate

Assume one shared symmetric customer-managed KMS key for all tenants. AWS KMS lists that key at **$1/month** and a free tier of **20,000 KMS requests/month** across regions; additional symmetric requests are **$0.03 per 10,000**. Cognito Lite/Essentials lists **10,000 monthly active users free** for direct or social sign-in. SAML/OIDC-federated users have a 50-MAU free allowance, and machine-to-machine token requests have no free tier ([AWS KMS pricing](https://aws.amazon.com/kms/pricing/), [Cognito pricing](https://aws.amazon.com/cognito/pricing/)).

| Scenario | Cognito | KMS | Estimated total/month |
|---|---:|---:|---:|
| Up to 10,000 direct-login MAUs and 20,000 KMS operations | $0 | $1 key, requests within free tier | **$1** |
| Up to 10,000 direct-login MAUs and 100,000 KMS operations | $0 | $1 + 80,000 × $0.03 / 10,000 = $1.24 | **$1.24** |
| 100,000 direct-login MAUs and 100,000 KMS operations | about $495 | $1.24 | **about $496.24** |

The third row estimates the next 90,000 Cognito Lite MAUs at $0.0055 each after the first 10,000 free users; the current AWS pricing page gives this tiered rate. Each provider-key upload/replace and each just-in-time decrypt consumes KMS operations. If KMS automatic rotation is enabled, AWS currently adds key-storage charges for the first two rotations; re-check the current page before enabling it. Email/SMS delivery and advanced Cognito security features can add cost.

### Google Cloud KMS unit-cost comparison

Google Cloud KMS lists **$0.06 per active software key version/month** and **$0.03 per 10,000 cryptographic operations**. Its recurring free tier is **100 active key versions and 10,000 cryptographic operations per month**, but applies **only to key versions created using Cloud KMS Autokey**. The free allowance is aggregated across projects under a billing account. Autokey provisions CMEK keys for supported Google Cloud services; it is not a general free allowance for an application's arbitrary direct KMS `Encrypt`/`Decrypt` calls. FOGG's BYOK secret-encryption design should therefore budget standard Cloud KMS rates unless we specifically choose a supported Autokey resource design. At standard rates, one software key version costs about **$0.06/month**, plus **$0.06 for 20,000 operations** or **$0.30 for 100,000 operations**. Total: approximately **$0.12/month** and **$0.36/month**, respectively ([Cloud KMS pricing and free-tier limits](https://cloud.google.com/kms/pricing), [Autokey overview and supported purpose](https://docs.cloud.google.com/kms/docs/autokey-overview)).

Supabase Auth lists **50,000 MAUs on its Free plan** and **100,000 MAUs on Pro starting at $25/month**. Free projects pause after one week of inactivity and do not include automatic backups, so the free plan is suitable for a prototype, not an availability commitment ([Supabase pricing](https://supabase.com/pricing)). Pairing Supabase Auth with Cloud KMS would be about **$0.12/month** for 20,000 KMS operations on an active free project, or about **$25.12/month** on the Pro plan, before any other infrastructure. That is cheaper at low volume but adds a second cloud/security-provider boundary if FOGG is hosted elsewhere.

### Cost recommendation

**How to read the estimates:** key storage is the small monthly rent for keeping an active encryption-key version available. Cryptographic operations are the per-use charge when the service encrypts or decrypts. Each upload/replacement encrypts once and each provider invocation decrypts once. A single shared key keeps key-storage costs predictable; operation counts rise with credential use.

- **Now:** use local identity and KMS mocks; incremental cost is $0.
- **First hosted prototype:** use the identity provider and KMS already aligned with the chosen hosting provider. If hosting is AWS, Cognito plus one shared KMS key is a simple reference at about $1/month for the first 10,000 direct-login MAUs and first 20,000 KMS operations.
- **Do not create one KMS key per tenant initially.** A shared key with tenant-bound encryption context is cheaper and sufficient for this plan's isolation model. Per-tenant KMS keys or customer-controlled encryption keys are a later, separately costed security tier.
- Set cloud budgets/alerts before provisioning KMS or enabling paid identity features. Free-tier limits are account-level and must be checked against usage from all applications in that account.
- Do not assume Google Cloud's Autokey free allowance covers FOGG's direct BYOK encryption calls. Treat it as unavailable for this design unless implementation proves it uses Autokey-created keys within the documented supported-resource model.

## Acceptance criteria

- Every credential operation requires a validated principal and verified tenant membership.
- Tenant A cannot retrieve, decrypt, overwrite, delete, or invoke provider credentials belonging to tenant B.
- Ciphertext is bound to tenant, provider, and credential version; moving the ciphertext to another row makes decryption fail.
- Credentials are encrypted before persistence and never returned to the UI.
- Decryption happens only immediately before an authorized provider invocation; plaintext is not cached or checkpointed.
- Logs, traces, exceptions, tool records, and test failures contain no credential plaintext or authorization header.
- Stages 1–3 run locally for $0 and all security tests use fake identity/KMS/provider services.
- Production auth/KMS adapters remain disabled until configuration, cost, and tenant-isolation checks are complete.
