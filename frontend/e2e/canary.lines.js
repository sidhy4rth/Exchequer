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

// What the console shows instead of that field once the owner closes live
// tracing to officers (EXCHEQUER_CONSOLE=officers, components/Showroom.jsx).
// Home.test.jsx checks the closed console still shows this link.
export const OFFICER_SIGN_IN = 'Sign in as an officer to trace live'
