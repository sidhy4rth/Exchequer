// The usual shape of an NCRP acknowledgement number, as a soft note only.
//
// Source: MHA, "Standard Operating Procedure for (NCRP)-(CFCFRMS), Custody,
// Restoration of Money and Grievance Redressal", paragraphs 6.1(d) and 6.2(c):
// a portal complaint gets a 14-digit number starting with "2", a 1930 helpline
// complaint a 14-digit number starting with "3". Read from a copy of the SOP a
// bank publishes (https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf,
// PDF pages 12 and 13), the SOP the
// Meghalaya High Court notified on 28.04.2026.
//
// It never refuses or changes a number: older or other numbers may not fit.
// The same rule is backend/app/ncrp.py and citizen/src/api.js (ncrpNote).

export const NCRP_NOTE = 'NCRP acknowledgement numbers are usually 14 digits starting with 2 or 3 — check the number.'

/** NCRP_NOTE when `text` is given but is not the SOP's usual shape, else ''. Spaces and hyphens are ignored. */
export function ncrpNote(text) {
  const plain = String(text ?? '').replace(/[\s-]/g, '')
  return plain === '' || /^[23][0-9]{13}$/.test(plain) ? '' : NCRP_NOTE
}
