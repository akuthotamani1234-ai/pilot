<div style="font-family: 'Segoe UI', Inter, system-ui, -apple-system, Roboto, Arial, sans-serif; line-height: 1.6;">

# 📚 Blow AI – Project Documents

### All project documents in one place

| **Version** | 1.0 |
|---|---|
| **Date** | Oct 23, 2026 (all documents checked against the code Nov 4, 2026) |

---

## 1. Documents

1. **[PRD](01_PRD.md)** – what we are building, for whom, and what it must do
2. **[Architecture](02_ARCHITECTURE.md)** – how it is built and how the parts talk to each other
3. **[Rules](03_RULES.md)** – safety, quality and coding rules that must never be broken
4. **[Design](04_DESIGN.md)** – how the screens look and behave, and how data is stored
5. **[Execution Process](05_EXECUTION_PROCESS.md)** – what happens step by step during a run
6. **[Installation](06_INSTALLATION.md)** – what to install and how to run it
7. **[Architecture & Demo](09_ARCHITECTURE_AND_DEMO.md)** – architecture, status and a demo of the core loop (written Oct 27 for a review; status and limits kept current)
8. **[Reliable Results](11_RELIABLE_RESULTS.md)** – one feature per test, reconciled report numbers, the AutomationTestStore baseline and its fixes, measured before and after (a dated record of Oct 28: its numbers are not updated)

The file numbers have gaps (07, 08, 10, 12, 13): those were history documents, deleted on Nov 2 and 3, 2026. The
README and the git history replace them.

## 2. Where to Start

- **New to the project?** → [../README.md](../README.md) → PRD → Architecture
- **Want to install or deploy it?** → [../README.md](../README.md) → [../DEPLOYMENT.md](../DEPLOYMENT.md)
- **Want to run it?** → Installation → Execution Process
- **Changing the code?** → Architecture → Rules → [../backend/README.md](../backend/README.md) →
  [../tests/README.md](../tests/README.md) → [../CONTRIBUTING.md](../CONTRIBUTING.md)

## 3. Diagrams

- `images/architecture.svg` – high-level architecture
- `images/agent-pipeline.svg` – the 10 core agents and the self-healing loop (the visual check, review and
  integrations steps between them are listed in [Architecture 4.1](02_ARCHITECTURE.md))
- `images/user-flow.svg` – the user journey from link to report

## 4. Other Documents

- [../README.md](../README.md) – user guide (install, configure, run, output files, project structure)
- [../DEPLOYMENT.md](../DEPLOYMENT.md) – installing on another PC, updating, what never to copy
- [../CONTRIBUTING.md](../CONTRIBUTING.md) – working on the code: checks, tests, coding rules, commits
- [../SECURITY.md](../SECURITY.md) – reporting a security problem, and what the tool protects
- [../backend/README.md](../backend/README.md), [../frontend/README.md](../frontend/README.md),
  [../tests/README.md](../tests/README.md) – what is in each folder
- `accuracy/` – measured accuracy results of the benchmark runs

## 5. How to View

- In VS Code: open a `.md` file and press **Ctrl+Shift+V** to see the headings, tables and diagrams.

</div>
