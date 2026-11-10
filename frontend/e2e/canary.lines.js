// What the site canary (canary.spec.js) reads on the console to know every
// chain is live: the status line in the shell's sidebar (AppShell.jsx).
// AppShell.test.jsx renders the shell and checks it still says this, so the
// canary cannot be left looking for text the console no longer shows.
export const ALL_CHAINS_READY = /^All \d+ chains ready to trace$/

// The field the console opens on (routes/Home.jsx). Home.test.jsx renders
// the console and checks it still carries this label.
export const CONSOLE_FIELD = 'Payment hash or wallet'

// The investigator door's way in without an account (routes/SignIn.jsx),
// which the canary clicks. SignIn.test.jsx checks the door still says it.
export const DEMO_BUTTON = 'Look around as a demo'
