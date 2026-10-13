import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchSigningKey, verifyReport } from '../api'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// Public on purpose: the people who check an Exchequer report -- an
// exchange's compliance desk, a court -- are not users of the console. The
// check reads only the text pasted here and the server keeps nothing.

const VERDICT = {
  genuine: { tone: 'green', title: 'Genuine and unchanged' },
  changed: { tone: 'red', title: 'This report was changed' },
  unsigned: { tone: 'amber', title: 'Unsigned report' },
  foreign: { tone: 'amber', title: 'Signed by a different server' },
  invalid: { tone: 'red', title: 'Not an Exchequer report' },
}

function verdictOf(r) {
  if (!r.sealed) return 'invalid'
  if (r.signed && r.signature_ok && r.hash_ok) return 'genuine'
  if (r.signed && r.key_fingerprint && r.key_fingerprint !== r.this_server_key) return 'foreign'
  if (!r.signed) return r.hash_ok ? 'unsigned' : 'changed'
  return 'changed'
}

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

  const verdict = result && VERDICT[verdictOf(result)]
  return (
    <div className="citizen">
      <header className="citizen-top">
        <Link to="/" className="brand" style={{ textDecoration: 'none' }}><Mark size={20} /><span>Exchequer</span></Link>
        <span className="citizen-actions"><ThemeToggle /></span>
      </header>
      <main className="verify-body">
        <span className="micro">Verify a report</span>
        <h1>Was this report issued by Exchequer, unchanged?</h1>
        <p className="note">Paste a text report (Report&nbsp;(.txt) on a case) or drop the file. Every report ends in a SHA-256 content hash and an Ed25519 signature made with this server&apos;s private key: editing a single character breaks the signature, and nobody without the key can make a new one. Nothing you paste is stored.</p>
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
                  <dt>content hash</dt><dd>{result.hash_ok ? 'matches the text' : 'does not match the text'}</dd>
                  <dt>signature</dt><dd>{!result.signed ? 'none' : result.signature_ok ? 'valid' : 'invalid'}</dd>
                  {result.key_fingerprint && <><dt>signed with key</dt><dd>{result.key_fingerprint}</dd></>}
                </dl>
              )}
            </div>
          </div>
        )}
        {key && (
          <p className="note">
            This server signs with Ed25519 key <span className="mono">{key.fingerprint}</span>.{' '}
            <button className="quiet" onClick={downloadKey}>Download the public key</button>{' '}
            to check reports offline with OpenSSL.
            {!key.persistent && ' This key is temporary and changes when the server restarts.'}
          </p>
        )}
      </main>
    </div>
  )
}
