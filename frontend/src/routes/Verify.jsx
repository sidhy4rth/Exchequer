import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchSigningKey, verifyReport } from '../api'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// Public on purpose: the people who check an Exchequer report -- an
// exchange's compliance desk, a court -- are not users of the console. The
// check reads only the text pasted here and the server keeps nothing.

// One verdict per backend `status` (signing.verify_report), shown as given.
// A status this page does not know reads as a warning: nothing unfamiliar
// may ever look reassuring.
const VERDICT = {
  genuine: { tone: 'green', title: 'Genuine and unchanged' },
  genuine_earlier_key: { tone: 'green', title: 'Genuine, signed with an earlier Exchequer key' },
  forged_issuer: { tone: 'red', title: 'Forged: not signed by this server' },
  revoked_key: { tone: 'red', title: 'Signed with a revoked key' },
  text_added: { tone: 'red', title: 'Text was added after signing' },
  changed: { tone: 'red', title: 'This report was changed' },
  signature_missing: { tone: 'red', title: 'Signature missing' },
  damaged: { tone: 'red', title: 'Signature damaged' },
  unsigned: { tone: 'grey', title: 'Unsigned: cannot be verified' },
  unknown_key: { tone: 'grey', title: 'Cannot be verified here' },
  not_a_report: { tone: 'red', title: 'Not an Exchequer report' },
}
const UNKNOWN = { tone: 'red', title: 'Cannot be trusted' }

function signatureRow(r) {
  if (!r.signed) return r.status === 'signature_missing' ? 'missing' : 'none'
  if (r.status === 'unknown_key' || r.status === 'forged_issuer') return 'not checked (unknown key)'
  if (r.status === 'damaged') return 'damaged'
  return r.signature_ok ? 'valid' : 'invalid'
}

// A 64-hex fingerprint in groups of four, so it can be compared by eye.
const grouped = (fp) => (fp || '').match(/.{1,4}/g)?.join(' ') ?? ''

export default function Verify() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [key, setKey] = useState(null)

  useEffect(() => { fetchSigningKey().then(setKey).catch(() => {}) }, [])

  async function check(body) {
    setBusy(true); setError(null); setResult(null)
    try { setResult(await verifyReport(body)) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function onFile(file) {
    if (!file) return
    const body = await file.text()
    setText(body)
    check(body)
  }

  function downloadKey() {
    const url = URL.createObjectURL(new Blob([key.public_key_pem], { type: 'application/x-pem-file' }))
    const a = document.createElement('a')
    a.href = url; a.download = `exchequer-${key.fingerprint}.pub.pem`; a.click()
    URL.revokeObjectURL(url)
  }

  const verdict = result && (VERDICT[result.status] ?? UNKNOWN)
  return (
    <div className="citizen">
      <header className="citizen-top">
        <Link to="/" className="brand" style={{ textDecoration: 'none' }}><Mark size={20} /><span>Exchequer</span></Link>
        <span className="citizen-actions"><ThemeToggle /></span>
      </header>
      <main className="verify-body">
        <span className="micro">Verify a report</span>
        <h1>Was this report issued by Exchequer, unchanged?</h1>
        <p className="note">Paste a text report (Report&nbsp;(.txt) on a case) or drop the file. Every report ends in a SHA-256 content hash and an Ed25519 signature made with the issuing server&apos;s private key. They cover everything above the CONTENT HASH line, including the server that issued the report and its key; this check also rejects any text added below it. Nothing you paste is stored.</p>
        <div
          className="verify-drop"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files?.[0]) }}
        >
          <textarea
            className="mono"
            value={text}
            onChange={(e) => { setText(e.target.value); setResult(null) }}
            placeholder="EXCHEQUER CASE REPORT …"
            spellCheck={false}
            aria-label="Report text"
          />
        </div>
        <div className="verify-actions">
          <button className="primary" disabled={!text.trim() || busy} onClick={() => check(text)}>{busy ? 'Checking…' : 'Verify'}</button>
          <label className="button-like">
            Open a .txt file
            <input type="file" accept=".txt,text/plain" hidden onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
        </div>
        {error && <p className="error-line">{error}</p>}
        {verdict && (
          <div className={`card verify-result ${verdict.tone}`} role="status">
            <div className="head"><span className={`pill ${verdict.tone}`}>{verdict.title}</span></div>
            <div className="body">
              <p>{result.detail}</p>
              {result.sealed && (
                <dl className="verify-facts mono">
                  <dt>content hash</dt><dd>{!result.hash_ok ? 'does not match the text' : result.signature_ok ? 'matches the text' : 'self-consistent only (anyone can compute this)'}</dd>
                  <dt>signature</dt><dd>{signatureRow(result)}</dd>
                  {result.signature_ok && result.issued_by && <><dt>issued by</dt><dd>{result.issued_by}</dd></>}
                  {result.signature_ok && result.key_fingerprint && <><dt>signed with key</dt><dd>{grouped(result.key_fingerprint_sha256) || result.key_fingerprint}</dd></>}
                  {result.signature_ok && <><dt>official key</dt><dd>{result.official ? "yes: in Exchequer's published list" : 'not in the published list'}</dd></>}
                  {!result.signature_ok && (result.claimed_key || result.key_fingerprint) && <><dt>claimed key (not checked)</dt><dd>{result.claimed_key || result.key_fingerprint}</dd></>}
                </dl>
              )}
            </div>
          </div>
        )}
        {key && (
          <p className="note">
            This server signs with Ed25519 key <span className="mono">{grouped(key.fingerprint_sha256) || key.fingerprint}</span>
            {key.official && <> <span className="pill green">Official Exchequer key</span></>}.{' '}
            {key.keys_published_at && <>Compare it with the key <a href={key.keys_published_at} target="_blank" rel="noreferrer">Exchequer publishes</a>: a copy of this site signs with a key of its own. </>}
            <button className="quiet" onClick={downloadKey}>Download the public key</button>{' '}
            to check reports offline with OpenSSL.
            {!key.persistent && ' This key is temporary and changes when the server restarts.'}
          </p>
        )}
      </main>
    </div>
  )
}
