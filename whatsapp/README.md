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

- a phone must **link the session once** by scanning a QR, and stay linked;
- it is a real account, so WhatsApp can ban it if it is used to spam;
- it is an unofficial automation of WhatsApp Web, not a supported API.

## Run it

```bash
npm install
cp .env.example .env      # set WA_BRIDGE_TOKEN to match backend/.env
npm start                 # or: npm run link, which prints the QR in the terminal
```

Then link the sending phone — **WhatsApp → Linked devices → Link a device** —
by scanning either the terminal QR or the one the backend serves at
<http://localhost:8000/message/qr>. The registration section of the site shows
the same QR while the session is unlinked, and switches to "sending live from
…" once it isn't.

`GET /health` reports `status`: `starting` → `qr` → `connected`.

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
