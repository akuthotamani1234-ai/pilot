# Security

Qpilot opens websites, types into their forms, runs AI-written test code and holds API keys and test accounts,
so security problems matter. This page says how to report one and what the tool protects.

## Reporting a problem
Please **don't open a public issue** for a security problem. Use GitHub's private report instead: the repository's
**Security** tab → **Report a vulnerability**. Say what you found, how to reproduce it and what it could lead to.

Only the latest version on the `main` branch gets security fixes.

## What the tool protects
In short:
- **Only websites you may test.** Every run needs the confirmation "I own this website, or I have written permission
  to test it". Only the website's own host is opened (plus `ALLOWED_HOSTS`); private networks and cloud metadata
  addresses are blocked. Logout / delete / pay are never clicked unless allowed on staging.
- **AI-written code is checked and sandboxed.** An import allow-list before it runs, then its own process without API
  keys, with network and file guards, Windows memory and process limits and a time limit per test. This is not a
  container.
- **Secrets stay out of the output.** Keys and passwords are removed from logs, results, traces and AI requests. A
  test account given in the UI is used for that run only. A test account the tool created is stored encrypted for one
  Windows user (DPAPI) in `accounts/`.
- **The web UI is local only.** It answers on 127.0.0.1 / localhost, and every change needs a header that other
  websites can't send. It has **no login**, so never expose it on a network or a server (see
  [DEPLOYMENT.md](DEPLOYMENT.md#not-supported-yet-a-shared-server-or-docker)).
- **Testing GitHub code runs that code on your PC.** Only test repositories you trust.
- **Jira and Confluence text is data, never instructions to Qpilot.** Imported requirements are shown as text (never
  as HTML), quoted as evidence, and turned into tests only after a person accepts each idea. A requirement test is
  designed like your own instruction: the AI's code passes the same allow-list and sandbox, the browser stays on the
  website's host, and a step that would delete, pay or change data is refused. A test is "Passed" only when the
  engine's own checks passed.
- **Atlassian is read-only unless three people-level switches are on.** The read client refuses every write. Jira
  write-back (a results comment, a Bug linked to its story) needs: the server owner's `QPILOT_JIRA_WRITEBACK=1`, a
  workspace admin switching it on with a separate write token (`JIRA_WRITE_API_TOKEN`, never the read token), and a
  named reviewer approving each write after seeing the exact request. Each write is sent once (idempotency key and
  a marker read back from Jira before any retry) and audited. Outgoing text has secrets and token-like values removed.
- **Tokens are write-only.** Atlassian tokens are stored encrypted per workspace (DPAPI on Windows, owner-only file
  elsewhere), never returned by the API, logged or audited. A run's test password and AI key are used for that run
  only and are not stored with the execution.
- **A token stays with its site.** Each Atlassian site has its own token slot, a stored token is bound to the site it
  was saved for and is never handed out for another, and a connection moved to another site or account loses its
  token (audited). A saved test account of a target website is reused only for that same address.

## Keeping your own keys safe
- Your keys go in `.env`, which git ignores. Never commit it, and never send it by e-mail or chat.
- Give each key the smallest rights it needs. A `GITHUB_TOKEN` only needs Contents + Pull requests: write, on the
  repositories it fixes.
- If a key was committed or shared by mistake, revoke it at the provider at once and make a new one. Removing the
  commit is not enough.
