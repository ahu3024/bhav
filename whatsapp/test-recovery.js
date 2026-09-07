/**
 * Regression test for the detached-frame outage.
 *
 * WhatsApp Web reloads itself — after a QR scan, on an update, on a recovered
 * socket — and the reload detaches the puppeteer frame open-wa runs every call
 * through. Before this test existed, the bridge did not notice: `status` stayed
 * `connected` and every send from then on failed with "Attempted to use
 * detached Frame '<id>'" until a human restarted the process.
 *
 * open-wa is stubbed here, so this runs with no browser and no linked phone:
 * `die()` on the fake client reproduces exactly what a reload does to a real
 * one. Run with `npm test` in whatsapp/.
 */
const path = require('path')
const Module = require('module')
const { EventEmitter } = require('events')

const PORT = Number(process.env.TEST_PORT || 3997)
process.env.WA_BRIDGE_PORT = String(PORT)
process.env.WA_BRIDGE_TOKEN = ''
process.env.WA_SESSION_DIR = path.join(require('os').tmpdir(), 'bhav-wa-test-sessions')
process.env.WA_PROBE_MS = '200'

const detached = () =>
  new Error("Attempted to use detached Frame '8D7DA996DD2BC608E72AAB4B1335A299'.")

let creates = 0
let failCreate = false
const live = { current: null }

function makeClient() {
  creates += 1
  const me = { dead: false }
  const c = {
    async sendText(to) {
      if (me.dead) throw detached()
      return `true_${to}_MSGID${creates}`
    },
    async getChatById() { if (me.dead) throw detached(); return {} },
    async checkNumberStatus() {
      if (me.dead) throw detached()
      return { numberExists: true, canReceiveMessage: true }
    },
    async getConnectionState() { if (me.dead) throw detached(); return 'CONNECTED' },
    async getHostNumber() { return '918888888888' },
    async onMessage() { return true },
    onStateChanged() {},
    async kill() { me.dead = true; return true },
    /** What a WhatsApp Web reload does to the page the client holds. */
    die() { me.dead = true },
  }
  live.current = c
  return c
}

const stub = {
  create: async () => {
    if (failCreate) throw new Error('QR scan required')
    return makeClient()
  },
  ev: new EventEmitter(),
}

// server.js resolves @open-wa/wa-automate from whatsapp/; seed the cache first.
const id = require.resolve('@open-wa/wa-automate', { paths: [__dirname] })
require.cache[id] = Object.assign(new Module(id, null), {
  filename: id,
  loaded: true,
  exports: stub,
})

require(path.join(__dirname, 'server.js'))

const base = `http://localhost:${PORT}`
const post = async (route, body) => {
  const r = await fetch(base + route, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  return { code: r.status, json: await r.json() }
}
const health = async () => (await fetch(`${base}/health`)).json()
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failures = 0
function check(name, ok, extra) {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}${ok ? '' : '  ' + JSON.stringify(extra)}`)
  if (!ok) failures += 1
}

;(async () => {
  await sleep(300)
  check('links on boot', (await health()).connected)

  const first = await post('/send', { to: '8618127913', body: 'hi' })
  check('sends while healthy', first.code === 200 && first.json.sent, first)

  live.current.die()
  const after = await post('/send', { to: '8618127913', body: 'hi again' })
  check('a send that meets a dead page still delivers', after.code === 200 && after.json.sent, after)
  const h1 = await health()
  check('one rebuild, and back to connected', h1.reconnects === 1 && h1.status === 'connected', h1)

  live.current.die()
  const burst = await Promise.all(
    [1, 2, 3, 4, 5].map((n) => post('/send', { to: '8618127913', body: `burst ${n}` })),
  )
  check('five concurrent sends all deliver', burst.every((b) => b.code === 200 && b.json.sent),
    burst.map((b) => b.code))
  check('and they share one rebuild, not five', creates === 3, { creates })

  live.current.die()
  const chk = await post('/check', { to: '8618127913' })
  check('/check recovers too', chk.code === 200 && chk.json.on_whatsapp, chk)

  // Nobody sends anything: the liveness probe alone must notice.
  const before = (await health()).reconnects
  live.current.die()
  await sleep(900)
  const h2 = await health()
  check('the probe rebuilds an idle session', h2.reconnects === before + 1 && h2.status === 'connected', h2)

  // A rebuild that cannot relink is an unavailable session, not a bad number.
  failCreate = true
  live.current.die()
  const dead = await post('/send', { to: '8618127913', body: 'x' })
  check('an unrelinkable session answers 503', dead.code === 503, dead)
  check('and /health says failed', (await health()).status === 'failed', await health())

  console.log(failures ? `\n${failures} failed` : '\nall passed')
  process.exit(failures ? 1 : 0)
})()
