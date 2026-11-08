# Agent instructions

This repository contains a Discord bot deployed to isolated development and production environments. Read [docs/agent-development-design.md](docs/agent-development-design.md) for agreed autonomy boundaries and proposed future orchestration. The design is **not** evidence that automated deployment verification or agent resumption is implemented.

## Development workflow

- Use a feature branch and pull request for changes. Keep changes focused and add regression tests for behavior changes.
- Inspect the actual code, test layout, and GitHub Actions configuration before selecting commands. This repository uses Poetry for dependency management; the container runs Python 3.12. Do not assume every CI job uses Python 3.12 (check the workflow).
- Run the relevant existing tests and, where practical, the full test suite. Report commands, results, and any tests that could not run. Do not claim live Discord, Kubernetes, or production validation without evidence.
- Treat failures as actionable: inspect logs, fix root causes, and rerun tests. Stop and report if repeated attempts fail rather than looping indefinitely.
- Do not commit secrets, credentials, tokens, private message content, or raw sensitive logs. Mock external APIs in unit tests.

## Deployment and authorization boundaries

- Merging application changes into `main` triggers image publication and automatic **development** deployment via the existing GitOps pipeline. The operator has approved agent-driven merges into `main` **after required checks pass**; respect any more restrictive permissions or approval requirements in the current execution environment.
- Production promotion is **always manual**: do not trigger, approve, or merge production GitOps changes.
- `bturetzky/homelab-gitops` is authoritative for Kubernetes manifests. Do not change live Kubernetes deployments imperatively or assume the agent has cluster access.
- Ask for approval before significant architecture changes, new infrastructure or credentials, destructive operations, historical backfills, or enabling persistent memory writes.
- Do not access production secrets or use production Discord credentials for testing.
- Only one feature agent should own dev integration validation at a time. A successful CI build is not proof of a successful dev rollout.

## Design and documentation

- Follow the relevant feature design in `docs/` before implementation. Preserve approved decisions; surface unresolved choices instead of inventing policy.
- Update the corresponding feature document with significant decisions, implementation status, and observed validation. Distinguish implemented, proposed, and verified behavior.
- Keep `docs/agent-development-design.md` for cross-feature agent workflow decisions. Avoid creating a separate checklist or verbose session diary.
- Keep the PR summary useful: what changed, why, what was tested, and any remaining risks or manual verification.

## Safety for the initial Codex experiment

- Start with small, contained, testable changes. Do not modify GitOps, deploy infrastructure, create credentials, or enable background automation unless explicitly requested.
- No automated homelab verification runner or durable event-driven agent orchestration is assumed to exist yet.
