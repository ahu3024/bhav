/**
 * Bhav WhatsApp bridge — open-wa (https://open-wa.org) behind a tiny HTTP API.
 *
 * open-wa drives a real WhatsApp account through WhatsApp Web, so there is no
 * 24-hour customer-service window and no pre-approved template to wait on: a
 * farmer who never messaged us first still gets the alert. The cost is that a
 * phone has to link the session once by scanning a QR code, and that session
 * has to stay linked.
 *
 * It is a Node library and the rest of the backend is Python, so this process
 * owns the WhatsApp client and exposes exactly what the backend needs:
 *
 *   GET  /health          is the session linked, and to which number
 *   GET  /qr              the pairing QR as a PNG (only while unlinked)
 *   GET  /qr.txt          the same QR as terminal-style ASCII
 *   POST /check           { to }        is this number actually on WhatsApp
 *   POST /send            { to, body }  send one message
 *
 * Every route except /health needs `Authorization: Bearer $WA_BRIDGE_TOKEN`
 * when that variable is set. Set it — this process can message anyone.
 */

const fs = require('fs')
const path = require('path')
const express = require('express')
const qrTerminal = require('qrcode-terminal')
const { create, ev } = require('@open-wa/wa-automate')
const waPuppeteerConfig = require('@open-wa/wa-automate/dist/config/puppeteer.config')

const PORT = Number(process.env.WA_BRIDGE_PORT || 3001)
const TOKEN = process.env.WA_BRIDGE_TOKEN || ''
const SESSION_ID = process.env.WA_SESSION_ID || 'bhav'
const SESSION_DIR = process.env.WA_SESSION_DIR || path.join(__dirname, '.sessions')
const CHROME = process.env.WA_CHROME_PATH || undefined
const SHOW_QR = process.argv.includes('--show-qr')
// How often to prove the WhatsApp Web page is still alive. See DEAD_PAGE below.
const PROBE_MS = Number(process.env.WA_PROBE_MS || 30000)
const UA =
  process.env.WA_USER_AGENT ||
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'

fs.mkdirSync(SESSION_DIR, { recursive: true })

// open-wa hardcodes a Chrome/104 user agent, and WhatsApp Web now answers that
// with "update Chrome" instead of the app — window.Debug never loads and start-up
// dies on a 30s waitForFunction. Its own `customUserAgent` option is only read
// when `inDocker` is set (initializer.js:129), so it cannot fix this from config;
// overwrite the module's exported default, which browser.js reads at call time.
waPuppeteerConfig.useragent = UA

// --- live state -------------------------------------------------------------

const state = {
  status: 'starting', // starting | qr | connected | reconnecting | failed
  me: null,           // the linked phone number, once known
  qrPng: null,        // Buffer of the pairing QR, cleared once linked
  qrAscii: null,
  error: null,
  startedAt: new Date().toISOString(),
  lastSendAt: null,
  sent: 0,
  failed: 0,
  reconnects: 0,      // how often the WhatsApp Web page had to be rebuilt
}

// open-wa emits the QR as a base64 data URI each time it refreshes.
ev.on('qr.**', (qrBase64) => {
  const b64 = String(qrBase64).replace(/^data:image\/png;base64,/, '')
  state.qrPng = Buffer.from(b64, 'base64')
  state.status = 'qr'
})

// The raw pairing string — lets us render an ASCII QR you can scan from a
// terminal, which is the only option over SSH.
ev.on('qr.raw.**', (raw) => {
  qrTerminal.generate(raw, { small: true }, (ascii) => {
    state.qrAscii = ascii
    if (SHOW_QR) {
      console.log('\nScan this with WhatsApp → Linked devices → Link a device:\n')
      console.log(ascii)
    }
  })
})

// --- WhatsApp id handling ---------------------------------------------------

/** WhatsApp addresses a person as `<countrycode><number>@c.us`, digits only. */
function toChatId(raw) {
  let digits = String(raw || '').replace(/\D/g, '')
  if (!digits) throw new Error('empty phone number')
  // A bare 10-digit Indian mobile is the common case here.
  if (digits.length === 10) digits = `91${digits}`
  return `${digits}@c.us`
}

// --- HTTP -------------------------------------------------------------------

const app = express()
app.use(express.json({ limit: '256kb' }))

function requireToken(req, res, next) {
  if (!TOKEN) return next()
  const header = req.get('authorization') || ''
  if (header === `Bearer ${TOKEN}`) return next()
  return res.status(401).json({ error: 'bad or missing bearer token' })
}

app.get('/health', (_req, res) => {
  res.json({
    provider: 'open-wa',
    status: state.status,
    connected: state.status === 'connected',
    me: state.me,
    qr_available: Boolean(state.qrPng),
    reconnecting: state.status === 'reconnecting',
    reconnects: state.reconnects,
    error: state.error,
    started_at: state.startedAt,
    sent: state.sent,
    failed: state.failed,
    last_send_at: state.lastSendAt,
  })
})

app.get('/qr', requireToken, (_req, res) => {
  if (!state.qrPng) {
    return res
      .status(409)
      .json({ error: state.status === 'connected' ? 'already linked' : 'no qr yet' })
  }
  res.type('png').set('Cache-Control', 'no-store').send(state.qrPng)
})

app.get('/qr.txt', requireToken, (_req, res) => {
  if (!state.qrAscii) {
    return res
      .status(409)
      .json({ error: state.status === 'connected' ? 'already linked' : 'no qr yet' })
  }
  res.type('text/plain').set('Cache-Control', 'no-store').send(state.qrAscii)
})

app.post('/check', requireToken, async (req, res) => {
  if (!client && !reconnecting) return res.status(503).json({ error: 'not linked yet' })
  try {
    const chatId = toChatId(req.body.to)
    const result = await withSession((wa) => wa.checkNumberStatus(chatId))
    res.json({
      to: req.body.to,
      on_whatsapp: Boolean(result && result.numberExists),
      can_receive: Boolean(result && result.canReceiveMessage),
    })
  } catch (e) {
    res.status(400).json({ error: String(e.message || e) })
  }
})

app.post('/send', requireToken, async (req, res) => {
  const { to, body } = req.body || {}
  if (!to || !body) return res.status(400).json({ error: 'to and body are required' })
  // A rebuild in flight is a few seconds, not a failure — wait it out rather
  // than telling a farmer who just registered to go and scan a QR code.
  if (reconnecting) await reconnecting
  if (!client || state.status !== 'connected') {
    return res.status(503).json({
      error: 'whatsapp session not linked',
      hint: 'run `npm run link` in whatsapp/ and scan the QR with the sending phone',
      status: state.status,
    })
  }
  const chatId = toChatId(to)
  try {
    const id = await sendWithRetry(chatId, body)
    state.sent += 1
    state.lastSendAt = new Date().toISOString()
    res.json({ sent: true, id: String(id), to: chatId })
  } catch (e) {
    state.failed += 1
    const msg = String((e && e.message) || e)
    console.error(`[bridge] send to ${chatId} failed: ${msg}\n${(e && e.stack) || ''}`)
    // A rebuild that could not relink is an unavailable session, not a bad
    // recipient — answer the way an unlinked bridge does so the backend gives
    // the "scan the QR" advice instead of blaming the number.
    if (state.status !== 'connected') {
      return res.status(503).json({
        sent: false,
        to: chatId,
        error: 'whatsapp session not linked',
        status: state.status,
        detail: msg,
        hint: 'the session dropped and could not be relinked — run `npm run link` in whatsapp/ and scan the QR with the sending phone',
      })
    }
    res.status(502).json({
      sent: false,
      to: chatId,
      error: msg,
      hint: isDeadPage(e)
        ? 'The WhatsApp Web session dropped mid-send and is being relinked. ' +
          'Nothing needs scanning — try again in a few seconds.'
        : /Not a contact|reading '(get|_get)'/i.test(msg)
          ? 'Unlicensed open-wa will only message numbers already saved as contacts on the linked phone (' +
            (state.me || 'the sending account') +
            '). Save this number as a contact there, or buy a licence at https://get.openwa.dev'
          : undefined,
    })
  }
})

/**
 * sendText does NOT reject on every failure — it can resolve with a string like
 * "ERROR: Not a contact. Unlock this feature ... getting a license", which would
 * otherwise be reported as a successful send. Anything that is not a message id
 * is treated as a failure here; a broadcast that claims to have delivered
 * nothing is worse than one that admits it failed.
 */
function assertSent(result) {
  const value = String(result)
  if (result === false || value.startsWith('ERROR:') || value === 'undefined') {
    throw new Error(value.replace(/^ERROR:\s*/, ''))
  }
  return value
}

/**
 * Unlicensed open-wa refuses to message a number that is not already a contact
 * on the linked phone. Touching the chat first occasionally materialises it;
 * when it does not, the error from assertSent is the honest answer.
 */
async function sendWithRetry(chatId, body) {
  return withSession(async (wa) => {
    try {
      return assertSent(await wa.sendText(chatId, body))
    } catch (e) {
      const msg = String((e && e.message) || e)
      if (isDeadPage(e)) throw e // withSession reconnects and calls us again
      if (!/reading '(get|_get)'|Not a contact/i.test(msg)) throw e
      console.warn(`[bridge] no chat for ${chatId}; materialising it and retrying`)
      try {
        await wa.getChatById(chatId)
      } catch {
        /* the chat still may not exist — the retry below is what decides */
      }
      return assertSent(await wa.sendText(chatId, body))
    }
  })
}

// --- the Chrome profile ------------------------------------------------------

/**
 * open-wa keeps the linked account in a Chrome profile beside the session data
 * (browser.js:509 builds the path as `<sessionDataPath>/_IGNORE_<sessionId>`).
 * That profile is the linkage — delete it and the phone has to scan a QR again.
 */
const PROFILE_DIR = path.join(SESSION_DIR, `_IGNORE_${SESSION_ID}`)

/**
 * Chrome refuses to reuse a profile another Chrome still holds, and marks it
 * `SingletonLock -> <host>-<pid>`. If the process died without cleaning up —
 * SIGKILL, an OOM, a crash, a power cut — the lock outlives it, and the next
 * launch does not fail loudly: it stalls, and the bridge dies 30 seconds later
 * on `Navigation timeout of 30000 ms exceeded` while loading WhatsApp Web. The
 * error names the network, so it sends you looking in entirely the wrong place.
 *
 * A lock whose pid is gone is garbage. Clear it — but only then, because a live
 * pid means a second bridge really is running and must not be trampled.
 */
function clearStaleProfileLock() {
  const lock = path.join(PROFILE_DIR, 'SingletonLock')
  let target
  try {
    target = fs.readlinkSync(lock)
  } catch {
    return // no lock, or not a symlink — nothing to clean up
  }

  const pid = Number(String(target).split('-').pop())
  if (Number.isInteger(pid) && pid > 0) {
    try {
      process.kill(pid, 0) // signal 0 only asks "is this pid alive?"
      console.warn(`[bridge] profile is locked by live pid ${pid} — is another bridge running?`)
      return
    } catch (e) {
      if (e.code === 'EPERM') {
        console.warn(`[bridge] profile locked by pid ${pid}, owned by another user — leaving it`)
        return
      }
      /* ESRCH: the pid is gone, so the lock is stale */
    }
  }

  for (const name of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
    try {
      fs.unlinkSync(path.join(PROFILE_DIR, name))
    } catch {
      /* already gone */
    }
  }
  console.warn(`[bridge] cleared a stale Chrome profile lock (dead pid ${pid})`)

  // Chrome also records the unclean exit and offers to restore the session on
  // the next launch, which gets in the way of a headless boot.
  const prefs = path.join(PROFILE_DIR, 'Default', 'Preferences')
  try {
    const d = JSON.parse(fs.readFileSync(prefs, 'utf8'))
    if (d.profile && d.profile.exit_type !== 'Normal') {
      d.profile.exit_type = 'Normal'
      d.profile.exited_cleanly = true
      fs.writeFileSync(prefs, JSON.stringify(d))
      console.warn('[bridge] reset the profile\'s crashed-exit flag')
    }
  } catch {
    /* no Preferences yet (first run), or unreadable — the launch decides */
  }
}

// --- session liveness --------------------------------------------------------

/**
 * Puppeteer errors that all mean the same thing: the WhatsApp Web tab we hold
 * is gone. WhatsApp Web reloads itself — once right after a QR scan, and again
 * whenever it ships an update or recovers a dropped socket — and a reload
 * detaches the frame open-wa evaluates every call through. From that moment
 * `sendText` throws "Attempted to use detached Frame '<id>'" forever, because
 * nothing about the reload changes `state.status`: the bridge keeps reporting
 * `connected` and keeps failing identically until someone restarts it.
 *
 * Only the browser side is broken. The session data on disk is untouched, so
 * rebuilding the client re-links the same account without a new QR scan.
 */
const DEAD_PAGE =
  /detached frame|execution context was destroyed|target closed|session closed|protocol error|frame (was )?detached|browser has disconnected|page has been closed|requesting main frame too early/i

function isDeadPage(e) {
  return DEAD_PAGE.test(String((e && e.message) || e))
}

let client = null
let reconnecting = null // the in-flight rebuild, shared by every waiting caller

/**
 * Rebuild the session. Serialised through `reconnecting` so that ten queued
 * sends hitting a dead page cause one reconnect, not ten competing ones — each
 * would otherwise launch its own Chrome against the same session directory.
 */
function reconnect(reason) {
  if (reconnecting) return reconnecting
  console.warn(`[bridge] session lost (${reason}); rebuilding`)
  state.status = 'reconnecting'
  state.error = reason
  state.reconnects += 1
  const old = client
  client = null
  reconnecting = (async () => {
    try {
      if (old) await old.kill('DEAD_PAGE')
    } catch {
      /* it is already gone — that is why we are here */
    }
    await connect()
  })()
    .catch((e) => {
      state.status = 'failed'
      state.error = String((e && e.message) || e)
      console.error('[bridge] reconnect failed:', state.error)
    })
    .finally(() => {
      reconnecting = null
    })
  return reconnecting
}

/**
 * Run one open-wa call; if it failed only because the page died, rebuild the
 * session and run it once more. Every call into open-wa goes through here — the
 * first send after a WhatsApp Web reload is otherwise guaranteed to fail, and
 * that failure is what a farmer sees as "could not be delivered yet".
 */
async function withSession(fn) {
  if (reconnecting) await reconnecting
  if (!client) throw new Error('whatsapp session not linked')
  try {
    return await fn(client)
  } catch (e) {
    if (!isDeadPage(e)) throw e
    await reconnect(String((e && e.message) || e))
    if (!client || state.status !== 'connected') {
      throw new Error('whatsapp session dropped and could not be relinked')
    }
    return await fn(client)
  }
}

// --- boot -------------------------------------------------------------------

/** Re-attached after every rebuild, because a new client has no listeners. */
function attachListeners(wa) {
  // Honour STOP so an opt-out over WhatsApp actually reaches the database.
  wa.onMessage(async (message) => {
    const text = String(message.body || '').trim().toUpperCase()
    if (text === 'STOP' || text === 'BAND' || text === 'बंद') {
      await forwardOptOut(message.from)
      await wa.sendText(message.from, 'You will not get more alerts. Reply START to resume.')
    } else if (text === 'START') {
      await forwardOptIn(message.from)
      await wa.sendText(message.from, 'You are back on the alert list.')
    }
  }).catch((e) => console.error('[bridge] could not attach onMessage:', String(e)))

  wa.onStateChanged((s) => {
    console.log(`[bridge] state -> ${s}`)
    if (s === 'CONFLICT' || s === 'UNLAUNCHED') {
      // Another device took the session over. Claiming it back re-navigates the
      // page, which is itself a frame detach — the probe below picks that up.
      wa.forceRefocus().catch((e) => console.warn('[bridge] forceRefocus:', String(e)))
    }
    if (s === 'CONNECTED') state.status = 'connected'
  })
}

async function connect() {
  clearStaleProfileLock()
  client = await create({
    sessionId: SESSION_ID,
    sessionDataPath: SESSION_DIR,
    multiDevice: true,
    headless: true,
    customUserAgent: UA,   // honoured only under inDocker; see the patch above
    // open-wa warns that multi-device is unreliable on plain Chromium; point
    // it at a real Chrome/Chromium binary and say so explicitly.
    useChrome: true,
    executablePath: CHROME,
    qrTimeout: 0,        // wait indefinitely for the scan
    authTimeout: 0,
    autoRefresh: true,
    qrRefreshS: 20,
    cacheEnabled: false,
    disableSpins: true,
    // Left false deliberately: open-wa's default is to process.exit() when the
    // tab closes, which turns a recoverable reload into an outage that needs a
    // human. reconnect() rebuilds the browser instead.
    killProcessOnBrowserClose: false,
    throwErrorOnTosBlock: false,
    blockCrashLogs: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  })

  state.status = 'connected'
  state.error = null
  state.qrPng = null
  state.qrAscii = null
  try {
    state.me = await client.getHostNumber()
  } catch {
    /* linked but the number isn't readable — not worth failing over */
  }
  console.log(`[bridge] linked as ${state.me || 'unknown number'}`)

  attachListeners(client)
}

/**
 * Notice a dead page on our own schedule rather than letting the next farmer's
 * registration be the thing that discovers it. getConnectionState is a bare
 * page.evaluate, so it throws the same detached-frame error a send would.
 */
function startLivenessProbe() {
  const timer = setInterval(async () => {
    if (!client || reconnecting || state.status !== 'connected') return
    try {
      await client.getConnectionState()
    } catch (e) {
      if (isDeadPage(e)) reconnect(String((e && e.message) || e))
      else console.warn('[bridge] liveness probe:', String((e && e.message) || e))
    }
  }, PROBE_MS)
  timer.unref()
}

async function start() {
  app.listen(PORT, () => {
    console.log(`[bridge] http://localhost:${PORT}  (session "${SESSION_ID}")`)
    if (!TOKEN) console.warn('[bridge] WA_BRIDGE_TOKEN is unset — /send is unauthenticated')
  })

  startLivenessProbe()
  await connectWithRetry()
}

/**
 * Linking can fail for reasons that pass on their own — a slow network, a
 * WhatsApp Web hiccup, a profile Chrome has not finished releasing. Dying into
 * `failed` on the first attempt means the alerts stay down until a human
 * notices, so keep trying with a widening gap.
 */
async function connectWithRetry(attempt = 1) {
  try {
    await connect()
  } catch (e) {
    state.status = 'failed'
    state.error = String((e && e.message) || e)
    const wait = Math.min(60000, 5000 * 2 ** (attempt - 1))
    console.error(
      `[bridge] link attempt ${attempt} failed: ${state.error}; retrying in ${wait / 1000}s`,
    )
    await new Promise((r) => setTimeout(r, wait))
    return connectWithRetry(attempt + 1)
  }
}

/**
 * Close the browser on the way out so Chrome releases the profile lock and
 * records a clean exit. Skipping this is what leaves the next boot stalling on
 * a stale lock — and SIGKILL, which cannot be caught, is exactly why
 * clearStaleProfileLock exists as the backstop.
 */
let shuttingDown = false
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    if (shuttingDown) return
    shuttingDown = true
    console.log(`\n[bridge] ${signal} — closing the browser cleanly`)
    // Deliberately not client.kill(): open-wa asks the browser to close and
    // then SIGKILLs its pid regardless (browser.js `kill`), which orphans work
    // Chrome was in the middle of. Closing the browser directly is the tidier
    // exit — though measured on this setup Chrome *still* leaves SingletonLock
    // behind and still records exit_type "Crashed", so this is a courtesy, not
    // a guarantee. clearStaleProfileLock on the next boot is the guarantee, and
    // it has to be: SIGKILL, an OOM and a power cut cannot be caught here.
    try {
      const page = client && typeof client.getPage === 'function' && client.getPage()
      const browser = page && !page.isClosed() && page.browser()
      if (browser) {
        await Promise.race([
          browser.close(),
          new Promise((r) => setTimeout(r, 10000)),
        ])
      }
    } catch {
      /* going down anyway; the next boot clears whatever is left */
    }
    process.exit(0)
  })
}

// Opt-out arrives on WhatsApp but the subscriber list lives in the Python
// backend, so hand it straight over. A bridge that swallowed STOP would leave
// people unsubscribing into the void.
const BACKEND = process.env.BHAV_API_URL || 'http://localhost:8000'

async function forwardOptOut(chatId) {
  await forward('/unsubscribe', chatId)
}
async function forwardOptIn(chatId) {
  await forward('/resubscribe', chatId)
}
async function forward(route, chatId) {
  const phone = `+${String(chatId).replace(/\D/g, '')}`
  try {
    await fetch(`${BACKEND}${route}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ phone }),
    })
    console.log(`[bridge] ${route} ${phone}`)
  } catch (e) {
    console.error(`[bridge] could not reach backend for ${route}:`, String(e))
  }
}

start()
