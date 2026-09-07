import { useEffect, useState } from 'react'
import {
  getMessagePreviews,
  getDeliveryStatus,
  subscribe,
  whatsappQrUrl,
  friendlyError,
  LANG_NAMES,
  type Lang,
  type MessagePreview,
  type DeliveryStatus,
} from '../api'

export default function GetAlerts() {
  const [lang, setLang] = useState<Lang>('mr')
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const [preview, setPreview] = useState<MessagePreview | null>(null)
  const [delivery, setDelivery] = useState<DeliveryStatus | null>(null)
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  // open-wa rotates the pairing QR every ~20s and the session flips to linked
  // the moment someone scans it, so this panel has to keep looking rather than
  // read once — otherwise it shows a dead QR, or keeps asking for a scan that
  // already happened.
  const [qrNonce, setQrNonce] = useState(0)

  useEffect(() => {
    let alive = true
    getMessagePreviews()
      .then((d) => alive && setPreview(d))
      .catch(() => {
        /* backend down — the form still explains itself */
      })

    const poll = () =>
      getDeliveryStatus()
        .then((d) => alive && setDelivery(d))
        .catch(() => {})
    poll()
    const statusTimer = setInterval(poll, 5000)
    const qrTimer = setInterval(() => alive && setQrNonce((n) => n + 1), 15000)
    return () => {
      alive = false
      clearInterval(statusTimer)
      clearInterval(qrTimer)
    }
  }, [])

  // Once linked there is nothing left to poll for.
  useEffect(() => {
    if (!delivery?.whatsapp_ready) return
    setQrNonce(0)
  }, [delivery?.whatsapp_ready])

  const qrSrc = `${whatsappQrUrl()}?n=${qrNonce}`

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setState('sending')
    setMsg('')
    try {
      const res = await subscribe({
        phone,
        name: name || undefined,
        village_pin: pin || undefined,
        lang,
      })
      const w = res.welcome
      if (w?.sent) {
        setMsg(`Registered. The current signal is on its way to ${res.subscriber.phone} over ${w.channel}.`)
      } else {
        // Show the fix, not the raw provider string — "Not a contact. Unlock
        // this feature..." tells a farmer nothing about what to do next.
        setMsg(
          `Registered ${res.subscriber.phone}, but the message could not be ` +
            `delivered yet. ${w?.hint || w?.reason || ''}`.trim(),
        )
      }
      setState('done')
    } catch (err) {
      setMsg(friendlyError(err))
      setState('error')
    }
  }

  const bubble = preview?.texts?.[lang] ?? ''

  return (
    <section className="section section--white alerts" id="get-alerts">
      <div className="container inner">
        <div className="alerts__copy">
          <h2 className="section__title">Get the signal on WhatsApp</h2>
          <p className="prose">
            One message a week, in your language: what to do, by when, what it is
            worth in ₹/quintal, and the one reason behind it. Four lines, because
            it gets read standing in a mandi. Reply STOP any time.
          </p>

          <form className="alerts__form" onSubmit={onSubmit}>
            <div className="alerts__langs" role="group" aria-label="Language">
              {(Object.keys(LANG_NAMES) as Lang[]).map((l) => (
                <button
                  type="button"
                  key={l}
                  className={`alerts__lang${l === lang ? ' is-on' : ''}`}
                  onClick={() => setLang(l)}
                  aria-pressed={l === lang}
                >
                  {LANG_NAMES[l]}
                </button>
              ))}
            </div>

            <label className="alerts__label" htmlFor="ga-phone">
              Phone number
            </label>
            <input
              id="ga-phone"
              className="alerts__input"
              type="tel"
              required
              placeholder="98765 43210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />

            <div className="alerts__row">
              <div>
                <label className="alerts__label" htmlFor="ga-name">
                  Name <span className="alerts__opt">optional</span>
                </label>
                <input
                  id="ga-name"
                  className="alerts__input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div>
                <label className="alerts__label" htmlFor="ga-pin">
                  Village PIN <span className="alerts__opt">optional</span>
                </label>
                <input
                  id="ga-pin"
                  className="alerts__input"
                  inputMode="numeric"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                />
              </div>
            </div>

            <button className="btn btn--primary alerts__submit" disabled={state === 'sending'}>
              {state === 'sending' ? 'Registering…' : 'Send me the signal'}
            </button>

            {msg && (
              <p className={`bt-msg${state === 'error' ? ' bt-msg--err' : ''}`}>{msg}</p>
            )}

            {delivery && !delivery.configured && (
              <p className="alerts__note">
                The WhatsApp bridge isn’t running — start it with{' '}
                <code>npm start</code> in <code>whatsapp/</code>. You can still
                register; the next weekly signal goes out once it is up.
              </p>
            )}
            {delivery?.configured && delivery.qr_available && (
              <div className="alerts__note alerts__pair">
                <p>
                  The sending account isn’t linked yet. Scan this from the phone
                  that will send the alerts — WhatsApp → Linked devices → Link a
                  device.
                </p>
                <img
                  className="alerts__qr"
                  src={qrSrc}
                  alt="WhatsApp pairing QR code"
                  width={180}
                  height={180}
                />
              </div>
            )}
            {delivery?.whatsapp_ready && (
              <p className="alerts__note">
                Sending live from{' '}
                <code>{delivery.linked_number ?? 'the linked account'}</code> over
                open-wa — no 24-hour window, so the signal reaches you whether or
                not you have messaged us before.
              </p>
            )}
          </form>
        </div>

        <div className="alerts__phone" aria-hidden="true">
          <div className="alerts__screen">
            <div className="alerts__chat-head">Bhav</div>
            <div className="alerts__bubble">
              {bubble
                ? bubble.split('\n').map((line, i) =>
                    // The message separates its blocks with blank lines. An
                    // empty span collapses to nothing, so those need to be a
                    // spacer or the bubble reads as one dense wall.
                    line ? (
                      <span key={i} className="alerts__line">
                        {renderBold(line)}
                      </span>
                    ) : (
                      <span key={i} className="alerts__line alerts__line--gap" />
                    ),
                  )
                : <span className="alerts__line">Loading this week’s signal…</span>}
              <span className="alerts__time">now</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** WhatsApp renders *text* as bold; mirror that in the preview bubble. */
function renderBold(line: string) {
  const parts = line.split(/(\*[^*]+\*)/g)
  return parts.map((p, i) =>
    p.startsWith('*') && p.endsWith('*') && p.length > 2 ? (
      <b key={i}>{p.slice(1, -1)}</b>
    ) : (
      <span key={i}>{p}</span>
    ),
  )
}
