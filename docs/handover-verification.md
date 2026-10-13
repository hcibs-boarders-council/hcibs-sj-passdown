# Handover verification (QR / code): design proposal

Status: **design only (decision D11)**. Nothing here is implemented. It needs your approval because it adds a database migration and changes the last step of the claim workflow.

## Problem

At the moment the owner presses **Mark as passed on** in My Posts once the junior has collected the item. Nothing confirms the junior was actually there, and either side can forget to update the listing.

## Proposed flow

1. When the owner approves a claim, the server creates a **6-digit handover code** for that claim.
2. Only the claimant sees it: on My Claims and on the item page, as `482 913` (and optionally as a QR code).
3. At the meet-up, the owner opens the approved claim in My Posts and types the code, or scans the QR with their phone camera.
4. If the code matches, the claim becomes **Completed** and the item **Passed on**, exactly as **Mark as passed on** does today.

The claimant shows and the owner enters. That way, a correct code proves the claimant was present: the owner can only get it from them.

## Data model (one additive migration)

Three new fields on `Claim`, all with defaults or nullable. Existing rows are untouched.

| Field | Type | Purpose |
|---|---|---|
| `handover_nonce` | `CharField(32, blank=True)` | Random value set on approval and replaced by **Get a new code** |
| `handover_attempts` | `PositiveSmallIntegerField(default=0)` | Wrong guesses, for lock-out |
| `handed_over_at` | `DateTimeField(null=True)` | When the code was confirmed (audit trail) |

The code itself is never stored. It is derived on demand as six digits of `HMAC(SECRET_KEY, "<claim id>:<nonce>")`, so the claimant's page can always display it and the server can always check it, without the database holding anything that could be read and replayed. A new nonce (from `secrets.token_hex`) gives a new code.

## Rules (all enforced on the server)

- Only the item owner can submit a code, and only while the claim is **Approved**.
- After 5 wrong attempts the form locks. The claimant can press **Get a new code**, which sets a new nonce and resets the counter.
- The comparison uses `hmac.compare_digest`, which runs in constant time.
- Confirming locks the item, then the claim, inside `transaction.atomic()`. This is the same lock order as `update_claim`, so it can't deadlock with other claim actions.
- The code stops working as soon as the claim leaves Approved (released, cancelled or completed).
- **Mark as passed on** stays as a fallback, for example if the junior's phone is dead. It can be relabelled **Passed on without a code**.

## QR code (optional, second step)

- The QR encodes `https://<site>/account/posts/#handover-<claim id>-<code>`. Putting the code after `#` means browsers never send it to the server, so it stays out of access logs.
- A small script on My Posts reads the fragment, fills in the code, and focuses **Confirm handover**. The owner still presses the button, which sends a normal POST with a CSRF token.
- Rendering the QR as SVG needs one small pure-Python dependency, `segno` (no C extensions). Alternatively, ship version 1 with the 6-digit code only and add QR later.

## Screens

- **My Claims (approved):** "Your handover code: **482 913**", with Show QR and Get a new code buttons and a one-line explanation.
- **My Posts (approved claim):** a **Confirm handover** form with a 6-digit input (`inputmode="numeric"`, `autocomplete="one-time-code"`), a clear error after a wrong code, and a remaining-attempts message.
- **Item page:** the claimant's panel shows the same code card as My Claims.

## Tests to add

- The code is created on approval and is visible to the claimant only, not to the owner or other students.
- A correct code completes the claim and passes the item on. A wrong code changes nothing and counts an attempt.
- The form locks after 5 attempts, and a regenerated code unlocks it.
- A non-owner submitting is rejected (404). A claim that isn't Approved is rejected.
- The code stops working after release, cancel or complete.
- Two simultaneous confirmations complete the claim once (Postgres-only concurrency test, like the existing one).

## Questions for you

1. Should the claimant show the code and the owner enter it, as proposed, or the other way round?
2. Version 1 with the 6-digit code only, or include the QR (`segno`) straight away?
3. Should **Mark as passed on** stay available without a code?
