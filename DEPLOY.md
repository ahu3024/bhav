# Deploying Bhav

Three pieces, and only one of them is difficult:

| Piece | What it needs | Free tier? |
|---|---|---|
| **bhav-web** — the site | static files | yes |
| **bhav-api** — the signal | Python + ~1 GB of committed data | yes, with a caveat |
| **bhav-whatsapp** — delivery | a real Chromium, a disk, and to never sleep | **no** |

`render.yaml` describes all three. Push the repo to GitHub, then **Render → New →
Blueprint** and point it at this repo. Everything below explains what that file
is doing and what you have to fill in by hand.

---

## Before the first deploy: build the snapshot

The API ships with its data. That is what lets a brand-new container answer its
first request with a real signal instead of a 503.

```bash
cd backend
python -m scripts.make_seed        # data/bhav.db -> data/seed.db
git add data/seed.db models/model.pkl
```

**`data/seed.db` is not `data/bhav.db`.** The live database also holds
`subscribers` and `message_log` — real phone numbers, and the text of every
message sent to them. Committing that file would put those numbers in git
history, where deleting them later does not remove them, and in every image
built from the repo. `make_seed` copies across only the tables the model reads,
and refuses to write a snapshot that picked up anything a person created:

```bash
python -m scripts.make_seed --check
```

Run that in CI if you want it enforced. `data/bhav.db` is git-ignored and stays
on your machine.

> Check what you are about to ship. `scripts.seed_demo` writes a synthetic
> history as an offline safety net, and it is easy to ship that by accident. A
> real snapshot has ~44,000 mandi rows across ~25 markets; the demo one has a
> single market. `python -m scripts.make_seed` prints the row counts.

---

## The site

Static, free, nothing to configure but one value.

Vite inlines `VITE_API_URL` at **build** time, so it is a build setting, not a
runtime one — changing it needs a redeploy, not a restart. Set it in the Render
dashboard to the API's full URL, scheme included:

```
VITE_API_URL = https://bhav-api.onrender.com
```

(The blueprint marks it `sync: false` because a service reference yields a bare
hostname and YAML cannot prepend `https://` to it.)

---

## The API

Runs from `backend/Dockerfile`. Python 3.12 — not the newest — because lightgbm,
numpy and scikit-learn all publish wheels for it, so the build is a download
rather than a compile in an image with no compiler.

### The disk

```yaml
disk:
  name: bhav-data
  mountPath: /var/data
  sizeGB: 1
```

with `BHAV_DATA_DIR=/var/data`. On first boot `bhav/bootstrap.py` copies the
shipped snapshot onto the disk; from then on registrations survive every deploy.

**To run the API on the free plan instead**, delete the `disk:` block and change
`plan: starter` to `plan: free`. Leave everything else. The API still works —
the data is in the image — but the container filesystem is wiped on each deploy,
so registrations do not survive one. Free instances also sleep after 15 idle
minutes and take roughly 50 seconds to wake; the site stays readable through
that, because the browser renders its cached copy while the request is in
flight (see *Caching* below).

### Refreshing the data

Render cron jobs get their own filesystem and cannot write to another service's
disk, so the pipeline does not run on Render. Run it where the credentials are —
your machine — and ship the result:

```bash
cd backend
python -m scripts.fetch_all       # needs Earth Engine auth for NDVI
python -m scripts.build
python -m scripts.make_seed
git commit -am "data refresh" && git push
```

With `BHAV_SEED_MODE=refresh` (what the blueprint sets), the next deploy replaces
the pipeline tables on the disk from the new snapshot and **keeps every
subscriber**. Set it to `missing` if you would rather the disk always win.

### Environment

| Variable | What it does |
|---|---|
| `BHAV_DATA_DIR` | where the live SQLite file goes. Point at the disk. |
| `BHAV_MODELS_DIR` | same, for the pickles. |
| `BHAV_SEED_MODE` | `refresh` \| `missing` \| `never` — see above. |
| `BHAV_ADMIN_TOKEN` | **set this.** Guards everything that can message a real person. |
| `BHAV_CORS_ORIGINS` | comma-separated origins. Defaults to `*`; set it to your site. |
| `BHAV_CACHE_MAX_AGE` | seconds a browser may reuse a response. Default 300. |
| `BHAV_SUBSCRIBE_LIMIT` | registrations per IP per hour. Default 5. |
| `WA_BRIDGE_URL` | the bridge. Accepts `host:port` or a full URL. |
| `WA_BRIDGE_TOKEN` | must match the bridge's. |

`PORT` is honoured; the platform sets it.

### Health

- `GET /health` — liveness. Touches neither database nor model, so a slow query
  cannot fail a healthy deploy. This is the one Render checks.
- `GET /readyz` — readiness, with the reason when the answer is no: what the
  bootstrap did, whether the warm-up finished, whether an admin token is set.

### Without an admin token

`/broadcast`, `/message/send`, `/message/qr`, `/message/check`, `/message/log`
and `/subscribers` are open. That is right on localhost and wrong on a host — an
open `/broadcast` messages every subscriber, and an open `/message/qr` hands a
stranger a code that links **their** WhatsApp account to your deployment. The
API logs a warning at boot and `/readyz` reports `admin_token_set: false`.

---

## Delivery — the hard one

open-wa automates WhatsApp Web, so the bridge is a Node process driving a real
Chromium. Three consequences:

1. **It needs a container.** `whatsapp/Dockerfile` installs Chromium from the
   distro rather than letting Puppeteer download its own — that download is a
   common build failure, and when it fails npm rolls the whole install back and
   leaves `node_modules` empty.
2. **It needs a disk.** The linked account *is* a Chrome profile on disk
   (`WA_SESSION_DIR`). Without one, every deploy asks someone to scan a pairing
   QR again. `/health` reports `persistent_session: false` when it detects this.
3. **It cannot sleep.** A free instance stops after 15 idle minutes, and a
   WhatsApp Web session that keeps being torn down and re-established is how an
   account gets flagged. `starter` is the floor. Chromium plus Node in 512 MB is
   tight; if the container restarts under load, that is the OOM killer and the
   answer is `standard`.

It is deployed as a **private service** (`type: pserv`) — reachable from the API
and from nowhere else. That matters here more than anywhere: `/qr` hands out a
pairing code and `/send` messages arbitrary numbers from the linked account.

`WA_REQUIRE_TOKEN=1` makes the bridge refuse to boot without a token. A bridge
with no token looks perfectly healthy, and the first symptom of the mistake is
the account being banned.

### Linking the sending phone

The bridge is private, so you link it through the API, which re-exposes the QR
behind the admin token:

```
https://bhav-api.onrender.com/message/qr?token=<BHAV_ADMIN_TOKEN>
```

Open that in a browser and scan it from the sending phone — WhatsApp → Linked
devices → Link a device. A **409** means it is already linked, which is the
success case. The QR rotates every ~20 seconds; reload if it goes stale.

The site's registration form shows the same pairing panel, but only to someone
who arrives with `?admin=<token>` in the URL. Everyone else sees "the sending
account is being set up" — because handing a visitor's browser a live pairing
code is handing them the account.

Check delivery afterwards:

```bash
curl -H "Authorization: Bearer $BHAV_ADMIN_TOKEN" \
     https://bhav-api.onrender.com/message/status
```

### Not paying for it

Delete the `bhav-whatsapp` service and the two `fromService` entries that
reference it, and run the bridge on any always-on machine you have — a home
server, a spare VPS, a Raspberry Pi:

```bash
cd whatsapp && npm ci && npm start
```

Then point the API at it (`WA_BRIDGE_URL`) over a tunnel, and set the same
`WA_BRIDGE_TOKEN` on both sides. Everything else is unchanged: the API degrades
to "delivery unavailable" whenever the bridge is unreachable, and registrations
still work — they simply wait for the next broadcast.

---

## Caching — why the site does not hammer the API

The signal changes when the pipeline runs, which is daily at most. Three layers
keep a page load from costing anything it does not have to. Measured on the real
pages, in a headless browser:

| | before | after |
|---|---|---|
| cold landing page | 3 requests | 1 |
| landing → today's call | 3 requests | 0 |
| reload with a warm cache | 3 requests | 0 |
| revisiting a backtest date | 3 requests | 0 |
| an idle tab, per 90s | ~18 | 6 (three reaching the network) |

**`/snapshot`** returns the alert, the satellite series and the weather series in
one response — 84 KB, 9.8 KB gzipped. The page has one thing to wait for and one
object to cache instead of three.

**ETags keyed on the data version.** `backend/bhav/db.py` keeps a `data_version`
that only an ingest moves. A revalidating browser gets a 304 with no body unless
the pipeline has actually run.

> This also fixed a real bug. The version used to be the database file's mtime —
> and the API moved it itself every time it persisted an alert row while serving
> `/alert/today`. So the feature cache was cold on *literally every request*, and
> each one rebuilt the whole matrix from SQLite. Repeat requests went from ~600 ms
> to ~13 ms once writes stopped invalidating reads.

**Stale-while-revalidate in the browser** (`src/cache.ts`). The last answer is
rendered immediately from `localStorage`, then revalidated behind it. A page
that has been visited before shows content before an effect has run — which is
also what makes a sleeping free instance survivable: the reader sees the last
signal while the wake-up is in flight, rather than a spinner.

The site stays live throughout. Nothing is pinned beyond the data version it was
computed from, revalidation runs on an interval and when a tab regains focus,
and the moment an ingest bumps the version every key misses and the next request
rebuilds.

---

## Other hosts

Nothing here is Render-specific except `render.yaml`.

- **Fly.io / Railway / any container host**: both Dockerfiles honour `PORT` and
  bind `0.0.0.0`. Mount a volume, set `BHAV_DATA_DIR` / `WA_SESSION_DIR`.
- **The API on a Python buildpack** rather than Docker:
  `pip install -r backend/requirements.txt`, then
  `uvicorn bhav.api:app --host 0.0.0.0 --port $PORT` from `backend/`.
  `requirements.txt` is the serving set; `requirements-ingest.txt` adds Earth
  Engine and lxml, which the API never imports.
- **The bridge on a Node buildpack**: only if the platform provides a Chromium
  binary — point `WA_CHROME_PATH` at it. Most do not, which is why it ships as
  a container.
