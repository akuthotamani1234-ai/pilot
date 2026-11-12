# Security

Blow AI opens websites, types into their forms, runs AI-written test code and holds API keys and test accounts,
so security problems matter. This page says how to report one and what the tool protects.

## Reporting a problem
Please **don't open a public issue** for a security problem. Use GitHub's private report instead: the repository's
**Security** tab → **Report a vulnerability**. Say what you found, how to reproduce it and what it could lead to.

Only the latest version on the `main` branch gets security fixes.

## What the tool protects
The full rules are in [project-docs/03_RULES.md](project-docs/03_RULES.md). In short:
- **Only websites you may test.** Every run needs the confirmation "I own this website, or I have written permission
  to test it". Only the website's own host is opened (plus `ALLOWED_HOSTS`); private networks and cloud metadata
  addresses are blocked. Logout / delete / pay are never clicked unless allowed on staging.
- **AI-written code is checked and sandboxed.** An import allow-list before it runs, then its own process without API
  keys, with network and file guards, Windows memory and process limits and a time limit per test. This is not a
  container: see the rules document for its limits.
- **Secrets stay out of the output.** Keys and passwords are removed from logs, results, traces and AI requests. A
  test account given in the UI is used for that run only. A test account the tool created is stored encrypted for one
  Windows user (DPAPI) in `accounts/`.
- **The web UI is local only.** It answers on 127.0.0.1 / localhost, and every change needs a header that other
  websites can't send. It has **no login**, so never expose it on a network or a server (see
  [DEPLOYMENT.md](DEPLOYMENT.md#not-supported-yet-a-shared-server-or-docker)).
- **Testing GitHub code runs that code on your PC.** Only test repositories you trust.

## Keeping your own keys safe
- Your keys go in `.env`, which git ignores. Never commit it, and never send it by e-mail or chat.
- Give each key the smallest rights it needs. A `GITHUB_TOKEN` only needs Contents + Pull requests: write, on the
  repositories it fixes.
- If a key was committed or shared by mistake, revoke it at the provider at once and make a new one. Removing the
  commit is not enough.
