// What the site canary (canary.spec.js) reads on the console to know every
// chain is live: the status line in the shell's sidebar (AppShell.jsx).
// AppShell.test.jsx renders the shell and checks it still says this, so the
// canary cannot be left looking for text the console no longer shows.
export const ALL_CHAINS_READY = /^All \d+ chains ready to trace$/
