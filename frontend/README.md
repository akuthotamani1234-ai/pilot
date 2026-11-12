# frontend/ – the web UI

Plain HTML, CSS and JavaScript: there is no build step and no package to install. `backend/server.py` serves these
files at `/static/...` and the page at http://127.0.0.1:8000/.

| File | What it is |
|---|---|
| `chat.html` | the page: the chat in the middle, recent tests on the left, the to-do list on the right |
| `chat.css` | its look (light and dark, follows the system setting) |
| `chat.js` | its logic: the website check, the AI picker, the live progress, the review questions, the report card, "Apply fixes" |

The page loads its fonts from Google Fonts. Without internet it still works, with the PC's own fonts.

## How the page talks to the backend
Only through the JSON API of `backend/server.py`:

| Call | Used for |
|---|---|
| `GET /api/check?source=...` | is the website reachable (title, HTTP status, load time) |
| `GET /api/providers` | which AI providers and models can be chosen, and which keys exist in `.env` |
| `POST /api/runs` | start a run (the settings of the form) |
| `GET /api/runs/{job}` | the live progress: log lines, stages, pages |
| `POST /api/runs/{job}/stop` | stop a run (it still writes its report) |
| `GET` / `POST /api/runs/{job}/review` | the human review's questions and the answers |
| `GET /api/history`, `GET /api/runs/latest` | earlier runs |
| `GET /api/pages/{run}` | the page-by-page view: every page found, its type, features and its tests' results |
| `GET /api/report/{run}`, `/api/coverage/{run}` | the final report's data |
| `GET /api/cases/{run}` (+ `/download`), `/api/excel/{run}` (+ `/download`) | the test cases (JSON) and the Excel file |
| `DELETE /api/runs/{run}` | delete a run (and the site's baseline, if it came from that run) |
| `GET` / `POST /api/runs/{run}/repo-fix/...` | "Apply fixes to your code" (prepare, then create the Pull Request) |
| `GET` / `POST /api/runs/{run}/recheck` | 🔁 Re-check after a fix: only that finding's tests run again |
| `POST /api/visual/{run}/approve` | "Approve the new look" (visual check) |
| `GET` / `POST /api/schedules`, `DELETE /api/schedules/{id}` | ⏰ Repeat this test (scheduled tests) |

Every `POST` / `DELETE` must send the header `X-Agentic-QA: 1`. Browsers can't send that header from another website,
so another website open in the same browser can't start, stop or delete tests. The server also only answers to the
host names 127.0.0.1 / localhost. (`POST /api/hooks/run`, for a deploy script, proves itself with `WEBHOOK_TOKEN`
instead; the page never calls it.)

## Rules for changing the page
- Show text from a website or a run only through the escape helper (`esc(...)`): it may contain HTML.
- Never put an API key or a password into the page's storage or its address. The browser only remembers the last
  choices (AI provider, model, pages, watch in Chrome, advanced settings) and the websites you confirmed permission
  for.
- Keep the style of the surrounding code: 2-space indent, `const` / arrow functions, small helper functions.
