# Bhav WhatsApp bridge

Sends the weekly sell/wait alert over **[open-wa](https://open-wa.org)**, which
drives a real WhatsApp account through WhatsApp Web.

## Why not Meta's Cloud API

Meta only allows a free-form message within **24 hours** of the recipient's last
inbound message. Outside that window nothing sends but a pre-approved template.
A weekly alert to farmers who have never messaged us is exactly the case that
rule forbids — so the useful message either doesn't arrive or arrives as a
template you can't edit.

open-wa has no window and no template. The trade-offs are real and worth stating:

- **Unlicensed open-wa only messages numbers already saved as contacts on the
  linked phone.** Anything else comes back `Not a contact. Unlock this feature
  … getting a license`. Save the recipient as a contact on the sending handset,
  or buy a licence at <https://get.openwa.dev>. This is an open-wa restriction,
  not a WhatsApp one — and it is the thing most likely to bite during a demo.
- a phone must **link the session once** by scanning a QR, and stay linked;
- it is a real account, so WhatsApp can ban it if it is used to spam;
- it is an unofficial automation of WhatsApp Web, not a supported API.

`sendText` does not reject on every failure — it can *resolve* with a string
beginning `ERROR:`, which naive code reports as a successful send. `server.js`
validates the return value and treats anything that is not a message id as a
failure, so a broadcast never claims delivery it did not achieve.

## Run it

```bash
npm install
cp .env.example .env      # set WA_BRIDGE_TOKEN to match backend/.env
npm start                 # or: npm run link, which prints the QR in the terminal
npm test                  # session-recovery regression test, no browser needed
```

Then link the sending phone — **WhatsApp → Linked devices → Link a device** —
by scanning either the terminal QR or the one the backend serves at
<http://localhost:8000/message/qr>. The registration section of the site shows
the same QR while the session is unlinked, and switches to "sending live from
…" once it isn't.

`GET /health` reports `status`: `starting` → `qr` → `connected`, plus
`reconnecting` while a dropped session is being rebuilt and `reconnects` — how
many times that has happened since boot.

## "Attempted to use detached Frame"

WhatsApp Web reloads its own page: once right after a QR scan, and again
whenever it ships an update or recovers a dropped socket. A reload detaches the
puppeteer frame open-wa evaluates *every* call through, so from that moment
`sendText` throws `Attempted to use detached Frame '<id>'` — the browser side is
dead even though the account is still linked and the session data on disk is
fine.

Nothing about that reload changed `status`, so the bridge used to keep
reporting `connected` and keep failing identically until someone restarted it.
That is why the same error came back on every registration.

The bridge now treats those puppeteer errors as "the page is gone" and rebuilds
the session from the same `sessionDataPath` — same account, no new QR. Sends
that hit a dead page are retried on the fresh session, concurrent sends share
one rebuild rather than racing to launch a Chrome each, and a liveness probe
(`WA_PROBE_MS`, default 30s) notices an idle session dying so a farmer's
registration is not what discovers it. If the rebuild genuinely cannot relink,
`/send` answers `503` with the "scan the QR" advice instead of a `502` that
blames the recipient.

`killProcessOnBrowserClose` is deliberately off: open-wa's default is to
`process.exit()` when the tab closes, which turns a recoverable reload into an
outage that needs a human.

`npm test` reproduces the whole failure against a stubbed open-wa — no browser
and no linked phone required.

## API

| Route | Purpose |
|---|---|
| `GET /health` | session state, linked number, send counters (no auth) |
| `GET /qr` | pairing QR as a PNG, while unlinked |
| `GET /qr.txt` | the same QR as terminal ASCII |
| `POST /check` | `{to}` → is that number on WhatsApp |
| `POST /send` | `{to, body}` → send one message |

Everything except `/health` needs `Authorization: Bearer $WA_BRIDGE_TOKEN`.
**Set that token** — this process can message anyone from the linked account.

Inbound `STOP` / `START` are forwarded to the backend's `/unsubscribe` and
`/resubscribe`, so an opt-out over WhatsApp actually reaches the database
rather than being swallowed here.

## The user-agent patch

open-wa 4.76 hardcodes a `Chrome/104` user agent. WhatsApp Web now answers that
with "update Chrome" instead of the app, so `window.Debug` never loads and
startup dies on a 30-second `waitForFunction`. Its own `customUserAgent` option
is only read when `inDocker` is set (`initializer.js:129`), so it cannot fix
this from config — `server.js` overwrites the module's exported default instead.
Override with `WA_USER_AGENT` if WhatsApp starts rejecting Chrome/130 too.
