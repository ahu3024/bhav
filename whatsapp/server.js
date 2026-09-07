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
  status: 'starting', // starting | qr | connected | failed
  me: null,           // the linked phone number, once known
  qrPng: null,        // Buffer of the pairing QR, cleared once linked
  qrAscii: null,
  error: null,
  startedAt: new Date().toISOString(),
  lastSendAt: null,
  sent: 0,
  failed: 0,
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
  if (!client) return res.status(503).json({ error: 'not linked yet' })
  try {
    const result = await client.checkNumberStatus(toChatId(req.body.to))
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
  if (!client || state.status !== 'connected') {
    return res.status(503).json({
      error: 'whatsapp session not linked',
      hint: 'run `npm run link` in whatsapp/ and scan the QR with the sending phone',
      status: state.status,
    })
  }
  try {
    const chatId = toChatId(to)
    const id = await client.sendText(chatId, body)
    state.sent += 1
    state.lastSendAt = new Date().toISOString()
    res.json({ sent: true, id: String(id), to: chatId })
  } catch (e) {
    state.failed += 1
    res.status(502).json({ sent: false, error: String((e && e.message) || e) })
  }
})

// --- boot -------------------------------------------------------------------

let client = null

async function start() {
  app.listen(PORT, () => {
    console.log(`[bridge] http://localhost:${PORT}  (session "${SESSION_ID}")`)
    if (!TOKEN) console.warn('[bridge] WA_BRIDGE_TOKEN is unset — /send is unauthenticated')
  })

  try {
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
      killProcessOnBrowserClose: true,
      throwErrorOnTosBlock: false,
      blockCrashLogs: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    })

    state.status = 'connected'
    state.qrPng = null
    state.qrAscii = null
    try {
      state.me = await client.getHostNumber()
    } catch {
      /* linked but the number isn't readable — not worth failing over */
    }
    console.log(`[bridge] linked as ${state.me || 'unknown number'}`)

    // Honour STOP so an opt-out over WhatsApp actually reaches the database.
    await client.onMessage(async (message) => {
      const text = String(message.body || '').trim().toUpperCase()
      if (text === 'STOP' || text === 'BAND' || text === 'बंद') {
        await forwardOptOut(message.from)
        await client.sendText(message.from, 'You will not get more alerts. Reply START to resume.')
      } else if (text === 'START') {
        await forwardOptIn(message.from)
        await client.sendText(message.from, 'You are back on the alert list.')
      }
    })

    client.onStateChanged((s) => {
      console.log(`[bridge] state -> ${s}`)
      if (s === 'CONFLICT' || s === 'UNLAUNCHED') client.forceRefocus()
      state.status = s === 'CONNECTED' ? 'connected' : state.status
    })
  } catch (e) {
    state.status = 'failed'
    state.error = String((e && e.message) || e)
    console.error('[bridge] failed to start:', state.error)
  }
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
