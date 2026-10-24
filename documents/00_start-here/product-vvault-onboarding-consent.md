# Product ↔ VVAULT onboarding and consent contract

Recorded: October 22, 2026.
Status: owner-requested architecture specification and legal-copy review draft.
No onboarding component, API, storage gate, policy version, or receipt schema
is implemented or activated by this documentation change.

## Product boundary and CleanHouse evidence

CleanHouse is the main security product. VVAULT is the optional, separate paired data
product. The owner-designated canonical model is Chatty ↔ VVAULT: two distinct
products, independent signup/consent boundaries, then an intentional
authenticated handshake only when the user chooses VVAULT-backed features.
CleanHouse signup and its own consent stand alone and provide intended local
collectors, scans, and local data access without any VVAULT account. Only
optional remote storage, synchronization, and continuity capabilities depend
on VVAULT enrollment and linking. This designation is an owner requirement, not an
audit of Chatty's current implementation.

“Double signup” describes the optional paired-product path, never a requirement
for using CleanHouse. It means independently creating or authorizing each
product's account and accepting each product's applicable policies when the
user opts into VVAULT-backed features. An existing VVAULT
account can be authorized; a duplicate account is not required. Signing into
either product, matching email addresses, or using the same Google identity
does not authorize the other product or establish a storage link.

Repository evidence: `CLEANHOUSE.md`, sections “OVVAULTS” and “VVAULT /
OVVAULTS”, requires durable local evidence/outbox, authenticated preservation,
and independent CleanHouse session/product databases. `backend/vvault_sync.py`
describes a shared Files/Network outbox and owner-scoped authenticated receipts
for commits to `ovvaults.vault_files`. These establish that absolute local-only,
no-retention, and no-cloud-sync descriptions conflict with the architecture.
They do not establish live pairing, current authorization, or implementation of
the new consent separation specified here.

## Reusable storage planes and capability profiles

Every main product has a default/product-owned storage plane that works without
VVAULT. “Product-owned” identifies the product's operational responsibility; it
does not assert legal ownership of user data. Its physical location, capacity,
entitlement, and connectivity requirements are product-specific. “Default” does
not mean “on this device,” offline, unlimited, or free. Never label product
cloud as local just because it is the default plane.

CleanHouse's intended default file storage is on-device/local filesystem; its
existing local product/session databases and evidence outbox support that
capture. This is not a guarantee that every CleanHouse service is offline or
that every category of data uses the same storage. Other examples are
illustrative only: GRID Game Manager could expose a user-selected personal
drive such as a 2 TB disk; a cloud SaaS could include a bounded product-cloud
allowance such as 1 GB. Those numbers are not actual quotas, pricing, free-tier
commitments, or verified capabilities of either example product.

Each configured storage plane must declare the following capability profile.
Unknown values remain explicitly unresolved; they must not become promises in
UI copy. Default-product onboarding need not wait for optional VVAULT business
decisions, but a VVAULT offer cannot promise undisclosed capabilities.

| Profile field | Required meaning |
| --- | --- |
| `plane_id`, `operator`, `data_authority` | Distinct default-product and optional VVAULT responsibility boundaries |
| `location_type` | Device filesystem, user-managed drive/NAS, product cloud, or hybrid; identify subplanes for hybrid storage |
| `capacity_source` | Physical capacity, configured allocation, plan entitlement, or metered quota; identify the source of truth and stale/unknown status |
| `capacity_disclosure` | Approved limits and units, included quota, paid tiers, overage behavior, and eligibility; no inferred free allowance |
| `offline_availability` | Which operations work without connectivity, caching limits, and reconciliation behavior |
| `encryption_and_key_custody` | Verified at-rest/in-transit protection, key holders, and recovery model; no automatic end-to-end guarantee |
| `retention` | Category-specific retention and approved amendment/deletion constraints for each plane |
| `export_deletion_ownership` | Responsible product/operator, scope, independent receipts, and partial-failure reporting |
| `synchronization_eligibility` | Eligible categories, direction, redactions, history inclusion, and authorized destination |
| `failure_semantics` | Full/read-only/offline/permission/quota/service failures, retry/backlog behavior, and effect on each capability |
| `display_labels` | Accurate profile-derived labels: Included storage, On this device, Your connected drive, Product cloud, or a hybrid explanation |

“Included storage” is appropriate only when the product profile establishes
inclusion; it does not itself mean free. VVAULT is a separate optional
data/continuity plane. Product-specific integration may add synchronization,
archival, recovery, cross-device continuity, or expanded storage. Do not claim
all benefits for every product, and never redefine, erase, or automatically
migrate the default plane when linking VVAULT.

The profile also configures offer timing (during onboarding or later), optional
benefits, eligibility, labels, disclosures, and separate-account handoff. The
invariant is independent optional consent and explicit revocable linking, not
identical screens or compulsory double signup. CleanHouse-specific “local”
wording below refers only to its on-device profile. Shared interfaces and state
names use default-plane language so they can also describe cloud products.

## Independent decisions and presentation

1. Authenticate/create the main-product account; review that product's Terms,
   Privacy Notice, and EECCD. Use its existing provider-aware confirmation.
2. At the product-configured time, offer only its supported optional VVAULT
   benefits with an equally clear action to continue using its default plane.
   For CleanHouse this may say “Continue on this device”; for a cloud product,
   use “Continue with Product cloud” or approved profile-specific wording.
   Declining must complete standalone onboarding without a VVAULT account,
   repeated blocking prompts, or loss of intended default-plane functionality. Only
   after an explicit opt-in, independently authenticate/create or authorize the VVAULT account and review
   VVAULT's own applicable policy versions on its trusted product surface.
3. Present a separate storage-link review: both account identities, destination,
   eligible data categories, selected scope, transfer trigger, backlog treatment,
   withdrawal behavior, and export/deletion ownership. Nothing is prechecked.
4. Explicitly authorize the bounded link, complete the authenticated handshake,
   and obtain a verified link receipt before enabling remote transfer.

The compact CleanHouse policy popup remains a product-policy review, not a
combined signup or storage authorization screen. Its checkbox must not carry
VVAULT terms or storage permission. Standalone legal pages retain their current
editorial shell, soft-green date tag, and direct availability. The reusable
storage-link review is a separate future component; this task adds no new UI
controls or routes. The profile-specific continue action completes the
standalone product path subject only to main-product access and entitlement
requirements, without implying VVAULT storage or an offline guarantee.
Do not label VVAULT signup as mandatory, treat a declined offer as a failed
CleanHouse setup, or require the user to create an unused data-product account.

For CleanHouse, show local collection and VVAULT preservation separately.
For other products, distinguish their default plane from VVAULT even when both
are remote services. A missing link
means “VVAULT not linked — optional remote preservation is off,” not “collector failed.”
Collector failures must still be reported when independently observed. Missing
main-product consent continues to deny protected access under the existing
policy gate; this contract does not relax it.

## Reusable component configuration and interfaces

Configuration supplies `product_id`, product name/mark/theme, trusted signup and
policy URLs, policy keys/versions/content digests, VVAULT product identity,
allowed return origins/routes, eligible scope labels, destination descriptions,
the storage capability profiles above, per-plane data disclosures, offer timing,
supported benefits, support contacts, and owner-approved legal copy.
Branding and copy cannot override the authorization rules. Missing required
disclosures or unapproved placeholders make the linking action unavailable.
All names below are proposed interfaces, not existing endpoint names.

| Interface | Required result / boundary |
| --- | --- |
| `getProductAccess()` | Main-product authentication, applicable policy receipts, and available reauthentication methods; no secrets in UI |
| `getDataProductAccess()` | Independently verified VVAULT account and policy status; no inference from main-product login |
| `getStorageLink()` | Link ID, identities, scope, destination, policy versions, authorization state, expiry/revocation, and receipt verification |
| `beginStorageLink(scope, returnRoute)` | Explicit user intent, allowlisted product return route, short-lived single-use challenge bound to accounts, destination, and scope |
| `completeStorageLink(challenge, proof)` | Server-verified cross-product response and current consents; reject mismatches, expiry, reuse, or untrusted redirects |
| `authorizeTransfer(batch)` | Recheck current link, required consents, scope, and revocation before every dispatch/retry; deny on unknown status |
| `revokeStorageLink(linkId)` | Stop new dispatch immediately, revoke remote grant, retain pending/confirmed status and revocation receipt |
| `getStorageProfiles()` | Default and optional planes with declared location, capacity source, approved entitlements, capability/failure state, and accurate display labels |
| `getDataOperations()` | Separate default-plane and VVAULT export/deletion capabilities, ownership, constraints, and independently receipted results |

Provider-aware reauthentication uses available capabilities. Google-only accounts
must never receive a password confirmation prompt. Unavailable fresh proof
blocks the sensitive operation truthfully; neither a fabricated password nor
the other product's session substitutes for proof. Do not collect VVAULT
credentials inside CleanHouse or expose tokens in URLs, UI, or receipts.

## States and transfer rule

Account authentication and policy status are separate state dimensions for each
product; default-plane health and capabilities are another independent dimension
(including collector health for CleanHouse). Link state is:

| State | Presentation and remote-transfer behavior |
| --- | --- |
| `default_plane_only` | Standalone product under its own access/entitlement requirements; no VVAULT account or transfer; CleanHouse may label this local-only/on this device |
| `vvault_available_not_linked` | Optional, profile-specific VVAULT offer with a default-plane continue action; no VVAULT transfer |
| `unlinked` | No current link; intended default-plane features remain available under their own requirements; optional reconnect; no VVAULT transfer |
| `data_signup_required` | Only within a chosen VVAULT flow: explain the separate account boundary and allow return to default-plane use; no VVAULT transfer |
| `data_consent_required` | Only within a chosen VVAULT flow: direct to VVAULT policy review and allow return to default-plane use; no VVAULT transfer |
| `link_review` | Show identities, scope, destination, and backlog decision; no remote transfer |
| `linking` | Explicitly chosen handshake verification in progress; no VVAULT transfer; default-plane use continues under its own requirements |
| `linked` | Transfer only within the current verified authorization |
| `reauthorization_required` | Changed/expired scope, identity, or policy proof; pause remote transfer |
| `degraded` | VVAULT service or authorization cannot be verified; pause VVAULT transfer and expose backlog separately; do not falsely mark the default plane or collectors failed |
| `revocation_pending` | Main-product dispatch to VVAULT stopped; VVAULT revocation acknowledgment unresolved |
| `consent_withdrawn` | Storage or required VVAULT consent withdrawn; stop VVAULT transfer; preserve intended default-plane use and distinguish pending revocation acknowledgment |
| `revoked` | Confirmed link withdrawal; no new VVAULT transfer; existing VVAULT data is not represented as deleted; default-plane use remains available |

Only optional VVAULT-backed capabilities use this gate. The main product's
default plane must not depend on any VVAULT state; its own connectivity, access,
capacity, and entitlement restrictions still apply. For CleanHouse, local
access, collectors, and scans must not depend on VVAULT. “Remote transfer” in
this contract means transfer to VVAULT, not ordinary default product-cloud
operations. VVAULT dispatch requires both authenticated account bindings, both required
policy acceptances, an explicit unexpired storage authorization for the exact
destination/scope, and a verified non-revoked handshake. Unknown means denied.
OAuth login, policy acceptance alone, cached UI state, or a transport credential
alone cannot satisfy this rule. This is the required future gate, not a claim
that the existing transport already enforces all of these conditions.

CleanHouse keeps its local product/session databases and local evidence/outbox.
Files/Network preservation evidence is an existing architectural category;
the precise transferable fields, redactions, retention, and defaults require
owner-approved configuration before the link review can be released. Do not
imply whole files, credentials, or unrelated content are eligible by default.
Remote transfer begins only after verified authorization and explicit scope.
Pre-link/backlogged evidence is excluded unless the review expressly includes
its categories and time range. Local backlog presence is not transfer consent.

## Receipts, withdrawal, and relinking

Keep separate immutable receipt types for main-product policy acceptance,
VVAULT policy acceptance, storage-link authorization, transfer acknowledgment,
and withdrawal/revocation. Each records its own receipt ID, type/schema version,
issuer/product, subject binding, policy key/version/content digest where
applicable, server timestamp, action, and verification reference. Link receipts
also bind both accounts, link ID, destination, scope/version, challenge ID,
expiry, and any prior receipt being superseded. Transfer receipts bind the
link authorization and idempotent evidence/batch ID. Do not place passwords,
session cookies, provider tokens, or raw evidence inside consent receipts.
Each authority owns its authoritative receipt; cross-product references do not
turn one product's acceptance into the other's. Never rewrite old receipts to
claim acceptance of new wording.

Withdrawal stops new remote dispatch and retries. Distinguish remote revocation
acknowledgment from the main product stopping dispatch; report in-flight/uncertain delivery honestly
and reconcile acknowledgments without replaying unauthorized batches. Default-plane
data remains under its own retention rules. Do not erase transcripts or
history as a side effect. Unlinking does not delete either account, withdraw
unrelated product terms, or prove already transferred data was deleted.

Relinking requires a new explicit review and verified receipt, even for the
same identities. Changed account, scope, destination, or policy versions must
not inherit the old grant. Reconcile idempotent transfer receipts before
authorized replay. Backlog inclusion must be chosen again; never silently
release a backlog merely because sign-in or connectivity recovered.

Each main product owns its default-plane export/deletion workflows according
to its profile; VVAULT owns its plane's workflows and authoritative completion
receipts. For CleanHouse the default file-storage plane is on-device. Present them
separately. Account deletion and unlinking are not equivalent. Cross-product
requests require explicit scope and independent results, including partial
failure. Exact retention, amendment-only evidence constraints, exceptions, and
deletion obligations remain legal/product-owner decisions; do not promise a
universal purge or retroactive removal of transferred data.

## Exact legal-copy review candidates

These are architecture corrections proposed for the three existing legal
documents, not activated legal terms. Keep rendered policy sources and their
November 9, 2025 update date unchanged until approved wording has a coordinated
acceptance rollout. `backend/api/auth.py::_cleanhouse_auth_docs()` derives both
version and digest from each document's bytes, so editing these files is also
a policy-version change, not merely presentation work. Deferring that mutation
avoids triggering re-consent with unreviewed copy. Existing receipts must retain
their original version references. The
current legal wording remains a known release blocker, not an endorsed account
of storage behavior. No effective date is invented by this draft.

| Source / conflicting wording | Proposed replacement for owner review |
| --- | --- |
| Terms §1: “self-contained AI hygiene and continuity suite” | “CleanHouse is the main security product and works independently of VVAULT. VVAULT is an optional, separate paired data product for authorized remote preservation.” |
| Terms §1: installing/initializing/interacting means “you consent to these terms” | “CleanHouse policy acceptance is recorded through an explicit review action. It does not authorize VVAULT signup, VVAULT policy acceptance, or cross-product storage.” |
| Terms §2: “intended for local deployment only” | “CleanHouse operates locally without a VVAULT account. You may optionally link the separate VVAULT data product for remote storage, synchronization, or continuity.” |
| Terms §4: “stores all data locally” and “does not sync with cloud servers” | “CleanHouse retains local operational data and evidence. Eligible evidence may be preserved in VVAULT only under a separate authenticated, scoped storage authorization following each product's account and consent flow.” |
| Privacy §1: “without collecting, retaining, or analyzing your personal data” | “CleanHouse processes local security evidence. Its local operation and separately authorized VVAULT preservation have distinct data-handling boundaries.” |
| Privacy §2: “ephemerally” / “discarded immediately” / “does not transmit” | “Local evidence and pending preservation records may persist. Remote preservation requires an explicitly authorized VVAULT link; the review must disclose eligible categories, scope, and whether historical evidence is included.” |
| Privacy §3: blanket no storage of files/paths or IP addresses | “The approved data-category disclosure must identify local evidence fields, remote-eligible fields, exclusions, and retention. Do not infer that observed paths or network identifiers are absent from security evidence.” |
| Privacy §5: optional cloud sync without the separate account boundary | “VVAULT is an optional, separate product with its own account and policy acceptance. CleanHouse's intended local functionality does not require VVAULT enrollment. Signing into CleanHouse does not sign you up for VVAULT or authorize storage there. Linking is explicit and revocable; declining or unlinking leaves local functionality available.” |
| Privacy §5: automatic end-to-end encryption / owner-only keys / zero server processing | Replace only with the verified transfer, encryption, key-custody, and processing disclosures approved for the actual deployment; no substitute guarantee is supplied in this draft. |
| EECCD §3: “Any temporary data is discarded post-session” | “Temporary processing data and retained security evidence must be distinguished. Local evidence and separately authorized VVAULT preservation follow their disclosed retention rules.” |

Legal-copy configuration placeholders requiring approval: `[LOCAL_DATA_FIELDS]`,
`[REMOTE_ELIGIBLE_FIELDS]`, `[EXCLUSIONS_AND_REDACTION]`, `[RETENTION]`,
`[TRANSFER_AND_KEY_CUSTODY]`, `[DATA_PRODUCT_POLICY_LINKS_AND_VERSIONS]`,
`[EXPORT_AND_DELETION_RULES]`, `[PROCESSING_AND_JURISDICTION]`,
`[CONTROLLERS_AND_CONTACTS]`, `[EFFECTIVE_DATE]`, `[DEFAULT_STORAGE_LOCATION]`,
`[CAPACITY_SOURCE]`, `[OFFLINE_CAPABILITIES]`, `[INCLUDED_QUOTA]`, `[PAID_TIERS]`,
`[OVERAGE_RULES]`, and `[ELIGIBILITY]`. Pricing and free allowances are unresolved
business policy; retention and eligibility also require product-specific owner
decisions. None of these placeholders or illustrative capacities establishes
what users receive for free. Placeholders must not appear
as completed disclosures in a released acceptance flow.

Review rather than silently rewrite unrelated promises: Privacy §§4/6/7
(training/profiling, crash-log handling, history purge), Terms §4's old data
category list and amendment rights, Terms §5's AI/provider restrictions, and
EECCD's broader automation/deletion claims. The owner/counsel must reconcile
these with actual capabilities and retention constraints. No legal compliance,
encryption guarantee, or enforceability conclusion is made here.

## Validation and release boundary

Documentation-only validation: verify the references above, compare the changed
contract against these boundaries, rerun the protected-surface verifier, and
confirm the index and existing presentation CSS remain unchanged. No database,
collector, auth, runtime, browser, or receipt mutation is required.

Future reusable acceptance must verify profile-derived labels (product cloud
is never mislabeled local), capacity/entitlement provenance without invented
allowances, configured offline/failure behavior, and preservation of the default
plane through linking/withdrawal. Test device, user-managed drive/NAS, cloud,
and hybrid profiles independently; product-specific screens need not match.

Future CleanHouse implementation acceptance must demonstrate: standalone CleanHouse signup
and consent without a VVAULT account; working intended local collectors, scans,
and local data after declining, unlinking, or withdrawing VVAULT consent; no
coercive repeated gate; independently optional VVAULT signup; refusal
to infer links from shared identity; unchecked separate storage review; safe
return routing; rejection of expired/replayed/mismatched handshake proofs;
blocked transfers under missing/withdrawn/unknown authorization; unchanged local
collector health; Google-only confirmation without passwords; independent
versioned receipts; revocation during queued/in-flight transfer; relink without
implicit backlog replay; and separate local/remote export/deletion results.
Use isolated test identities and focused tests, never accept policies for the
owner. Current tests of product-policy gating do not prove these future gates.

Release requires owner-approved legal text and policy versions, implemented and
tested interfaces, verified data disclosures, and separate live acceptance.
This contract alone satisfies none of those implementation or activation gates.
