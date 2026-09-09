# Deploying Bhav

Three pieces. `render.yaml` deploys two of them free, no card required:

| Piece | What it needs | In render.yaml? |
|---|---|---|
| **bhav-web** — the site | static files | yes, free |
| **bhav-api** — the signal | Python + ~1 GB of committed data | yes, free |
| **bhav-whatsapp** — delivery | a real Chromium, a disk, and to never sleep | **no — see below** |

The site and the signal work fully on their own — registration still takes a
phone number, `/delivery/status` just reports nothing is reachable yet, and the
form says so. There is no free way to run the WhatsApp bridge on Render: it
needs a disk (Render only sells those on paid plans) and an instance that never
sleeps (a free one stops after 15 idle minutes, and a WhatsApp Web session torn
down and rebuilt that often is how the linked account gets flagged). Add it
later — as a paid Render service, or self-hosted on any machine you already
leave running — see *Delivery* below.

Push the repo to GitHub, then **Render → New → Blueprint** and point it at this
repo. Everything below explains what that file is doing and what you have to
fill in by hand.

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

### Persisting data (optional, needs a paid plan)

`render.yaml` deploys the API on `plan: free` with no disk. That works fully —
the shipped snapshot (`data/seed.db`) is baked into the image, so every deploy
serves a real signal on its first request — but the container filesystem is
wiped on each deploy, so any registrations taken since the last one go with it.
Free instances also sleep after 15 idle minutes and take roughly 50 seconds to
wake; the site stays readable through that, because the browser renders its
cached copy while the request is in flight (see *Caching* below).

To keep registrations across deploys, add a disk and switch to a paid plan:

```yaml
plan: starter
disk:
  name: bhav-data
  mountPath: /var/data
  sizeGB: 1
envVars:
  - key: BHAV_DATA_DIR
    value: /var/data
  - key: BHAV_MODELS_DIR
    value: /var/data/models
```

On first boot `bhav/bootstrap.py` copies the shipped snapshot onto the disk;
from then on registrations survive every deploy.

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

Without a disk this happens automatically on every deploy — there's nothing
persisted to refresh. Once you add a disk (see above), `BHAV_SEED_MODE=refresh`
(what the blueprint sets) makes the *next* deploy replace the pipeline tables on
the disk from the new snapshot and **keep every subscriber**. Set it to
`missing` if you would rather the disk always win.

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

**Not deployed by default.** `render.yaml` ships only the site and the signal —
registration still works, `/delivery/status` reports nothing reachable, and the
form tells people so. This section is for when you're ready to add it.

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

### Adding it on Render (paid — needs a card)

`render.yaml` has the full service definition commented out at the bottom, with
the two lines it changes on `bhav-api`. Uncomment the `bhav-whatsapp` block,
swap the two `WA_BRIDGE_*` `sync: false` entries on `bhav-api` for the
`fromService` wiring shown right below them, and push. Re-run **Sync Blueprint**
in the Render dashboard and it will ask for a card at that point, because
`bhav-whatsapp` needs `plan: starter` and a disk.

It deploys as a **private service** (`type: pserv`) — reachable from the API
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

### Self-hosting it instead (free, no card)

Run the bridge on any always-on machine you already have — a home server, a
spare VPS, a Raspberry Pi:

```bash
cd whatsapp && npm ci && npm start
```

Expose it over a tunnel (Tailscale Funnel, Cloudflare Tunnel, ngrok — anything
that gives it a stable address), then on `bhav-api` in the Render dashboard set:

```
WA_BRIDGE_URL   = the tunnel's address (host:port or a full URL, either works)
WA_BRIDGE_TOKEN = the same value as WA_BRIDGE_TOKEN in whatsapp/.env
```

No blueprint change needed — these are the two `sync: false` fields already in
`render.yaml`. Everything else is unchanged: the API degrades to "delivery
unavailable" whenever the bridge is unreachable, and registrations still work —
they simply wait for the next broadcast. The trade-off is that delivery is only
as reliable as your machine staying on and the tunnel staying up.

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
