# Agent instructions

This is a Python 3.12 / Poetry 1.8.3 Discord bot with separate dev and production deployments. Read [docs/agent-development-design.md](docs/agent-development-design.md) and the relevant feature design before changing behavior.

## Approved first Codex feature experiment

- For an **operator-approved, contained feature**, Codex may implement changes on a feature branch, add/update regression tests and docs, open a PR, inspect CI failures, repair them with bounded retries, and merge its **own application PR** to `main` once required checks pass, subject to the agent's actual GitHub permissions. Do not bypass branch protections or checks.
- Run `make test` (or `poetry run python -m unittest discover -s tests -t .`) and relevant targeted tests; inspect the real workflow and dependencies before selecting commands. Report evidence, not assumptions.
- A merge to application `main` **automatically publishes an image and deploys to dev**. The post-deploy GitHub Actions `verify-dev` job runs on ARC and checks the expected digest, Argo CD sync/health, and Deployment readiness. Inspect that job's actual outcome before claiming dev rollout success. A passing rollout check is **not** a live Discord behavior test.
- If checks or deployment verification fail, inspect available logs, fix the root cause, and retry a reasonable bounded number of times; stop and report persistent failures. Never claim Codex can automatically resume on a CI event without an explicitly configured mechanism.
- Keep one feature agent at a time while using the shared dev environment. Do not conflate a successful CI build, verified Kubernetes rollout, and verified Discord interaction.

## Approval and security boundaries

- **Production promotion always requires operator action and review.** Do not trigger or merge production GitOps changes.
- `bturetzky/homelab-gitops` is authoritative for Kubernetes and Argo CD manifests. No imperative deployment mutations.
- Ask approval for significant architecture changes, new infrastructure/credentials, destructive operations, historical data backfills, or enabling persistent memory writes.
- Never commit or expose credentials, Discord message bodies, private memories, or sensitive logs. Mock external APIs in unit tests. Do not use production credentials for dev tests.
- The ARC runner has read-only, named-resource Kubernetes access to the dev bot Deployment and its Argo CD Application. Do not expand RBAC or use the runner to execute arbitrary cluster operations.

## Documentation

- Preserve approved feature design decisions and update feature docs with what was actually implemented/tested.
- Use [docs/deployment-workflow.md](docs/deployment-workflow.md) for CI/CD mechanics and [docs/engineering-roadmap.md](docs/engineering-roadmap.md) for broader engineering context. Avoid session diaries and duplicate GitOps infrastructure docs.
- PR summary: scope, tests, CI result, deployment verification result if available, and any remaining manual Discord smoke tests.
