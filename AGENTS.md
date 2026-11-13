# Agent instructions

This is a Python 3.12 / Poetry 1.8.3 Discord bot with isolated dev and production deployments. Before changing behavior, read [architecture](docs/architecture.md), the relevant [backlog](docs/backlog.md) item, and current code/tests. GitHub PR history is the record of previous implementation decisions; do not mistake old proposals for current behavior.

## Development and approval boundaries

- For an operator-approved, contained feature, an agent may implement on a branch, add regression tests, open a PR, inspect CI, fix bounded failures, and merge its own **application** PR after required checks pass if authorized. Never bypass branch protections.
- Run `make test` (or `poetry run python -m unittest discover -s tests -t .`) and relevant targeted tests. Report observed evidence, not assumptions.
- Merging application `main` publishes an image and automatically deploys to **dev**. The ARC `verify-dev` job checks digest, Argo sync/health, Deployment readiness and gateway startup. It does **not** prove a Discord feature works.
- Use one feature agent at a time against shared dev. A CI pass, Kubernetes rollout and human Discord acceptance are three distinct milestones.
- **Production promotion always requires operator review/action.** Do not trigger or merge production GitOps changes.
- `bturetzky/homelab-gitops` owns Kubernetes, Argo CD, Secrets and runtime deployment settings. Do not mutate live deployments imperatively.
- Obtain approval for major architecture/infrastructure changes, credentials, destructive operations, historical backfills and enabling persistent memory writes.
- Never commit secrets, real guild IDs, Discord messages, private memories or sensitive logs. Mock external services in tests; do not use production credentials for dev.
- ARC runner Kubernetes access is deliberately read-only and scoped; do not broaden it.

## Feature handoff

For user-visible changes, supply 2–4 concrete manual dev Discord prompts/actions, expected results, one negative/fallback case, prerequisites, and the PR/workflow/digest when known. Only claim human acceptance after the operator reports it. Do not silently promote to prod.

## Documentation maintenance rules

**Keep documentation small, current and nonduplicative.** The permanent Markdown inventory is:
- `README.md`: capabilities, quickstart and authoritative application environment-variable reference.
- `AGENTS.md`: agent behavior, approval gates and documentation rules.
- `docs/architecture.md`: **implemented** components, invariants, important tradeoffs and limitations.
- `docs/backlog.md`: **unfinished** features, actionable debt and explicitly pending operator verification.
- `docs/deployment.md`: CI/CD, promotion, rollback and verification boundaries.
- `docs/operations.md`: commands, diagnostics, backfills and concise manual acceptance procedures.
- `docs/tool-designs/`: **operator-approved exception** for independent, unimplemented on-demand LLM function assignments. The index links one actionable Codex handoff per file; remove or consolidate a design when shipped and accepted. Do not create other speculative design folders by default.

- Update the **existing owner document** when behavior changes. Do not create a new roadmap, status checkpoint, feature design, runbook or dated implementation diary by default. If a substantial new design genuinely needs a temporary document, get operator agreement and fold its durable decisions into the permanent docs when shipped.
- Describe **current code** as implemented only after checking it; label unmerged plans, CI-tested behavior, deployed behavior and operator-verified behavior separately. A green build is not live acceptance.
- Once work is shipped and accepted, **remove it from the backlog** and delete superseded verification instructions. Keep only important design rationale and current operating commands, not PR timelines, sample logs, token counts or historical checklists.
- Document pending verification only when genuinely outstanding. Do not reopen operator-confirmed acceptance without new evidence. Keep unfinished work in one backlog, not scattered across feature pages.
- Link to code, workflows and GitOps instead of duplicating configuration, infrastructure manifests or implementation details. Application env vars belong in README; GitOps is authoritative for deployed values.
- Fix links and stale statements in the same PR as a feature change. The approved tool-design folder is an explicit exception: individual Codex assignments need separate, self-contained handoffs. For any other Markdown file, first explain why the existing owner documents are unsuitable.
- Do not put real guild IDs, credentials, message contents, private memory summaries or sensitive operational output into documentation.
- Documentation-only maintenance may go directly through an ordinary reviewed PR; do not introduce runtime changes as part of cleanup.

PR handoff: scope, tests, CI result, dev deployment verification if available, and any remaining human Discord checks.
