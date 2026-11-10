// Text from outside this codebase (explorer tags, label lists, a scam token's
// own name) is shown in place of, or next to, an address. Characters that
// print nothing -- zero-width spaces, soft hyphens, bidi overrides and
// isolates -- can make such a name read as something it is not, or reorder
// the text around it. The server cleans tags before classifying them; this is
// the same cleaning at the point of display, for every source.

const HIDDEN = /\p{Cf}/gu // format characters: zero-width, soft hyphen, bidi controls
const CONTROL = /[\p{Cc}\u2028\u2029]+/gu // line breaks, tabs and other controls

/** `text` as the plain, one-line name it reads as; null and undefined as they are. */
export function plain(text) {
  if (text === null || text === undefined) return text
  return String(text).normalize('NFKC').replace(HIDDEN, '').replace(CONTROL, ' ').replace(/\s+/g, ' ').trim()
}

/** One of Exchequer's own sentences that quotes outside text, such as an
 * address: what prints nothing removed and kept on one line, as plain() does,
 * but its own punctuation (an ellipsis) kept as written. */
export function plainSentence(text) {
  if (text === null || text === undefined) return text
  return String(text).replace(HIDDEN, '').replace(CONTROL, ' ').replace(/\s+/g, ' ').trim()
}
