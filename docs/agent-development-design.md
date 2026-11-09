# Autonomous feature development — design and decisions

**Status (2026-11-08):** First Codex Cloud autonomous pipeline experiment completed successfully (PR #38). Code implementation, local tests, PR CI, self-merge, image publication, GitOps dev deployment, ARC verification, and PR feedback were observed. Codex stayed active and polled GitHub; **event-driven resumption was not tested**. CI failure repair and live Discord behavior were also not tested.

## Goal and autonomy

Use cloud-hosted Codex to implement a contained, approved feature in `bturetzky/chatgpt-discord-bot`, add tests/docs, open a PR, repair CI failures, and merge its own application PR after required checks pass (where permissions allow). Application `main` automatically deploys to the isolated dev bot. Keep one feature agent at a time.

**Human gates:** Significant architecture changes, new infrastructure or credentials, destructive operations, historical backfills, and enabling persistent memory writes need approval. Production promotion always remains manual and reviewed. Codex must not modify live Kubernetes resources or deploy to production.

## Implemented pipeline (verified 2026-11-08)

1. PR checks run Python unit tests and Docker build; PR builds do not publish.
2. Merge to application `main` builds/pushes immutable GHCR image; GitHub Actions updates the dev GitOps image digest via an automatically merged dev-only GitOps PR.
3. Argo CD auto-reconciles `discord-dev` by normal polling; **no inbound GitHub webhook** is used.
4. GitHub Actions `verify-dev` runs on the ephemeral `discord-dev-verify` ARC scale set inside Kubernetes. `scripts/verify_discord_dev.py` polls for the expected image digest, Argo CD Synced/Healthy, and ready/updated Deployment replicas; timeout 10 minutes (job limit 12 minutes). Operator confirmed the first end-to-end verification run passed.
5. Production is promoted separately through `promote-prod.yml`, which opens a review-only GitOps PR for the dev-pinned digest. No automatic production promotion.

The ARC runner has a dedicated ServiceAccount with `get` on only the named `discord-dev` Deployment and named `argocd/discord-dev` Application. No Kubernetes Secrets or write permissions. GitOps configuration and RBAC are authoritative in `bturetzky/homelab-gitops`; ARC runner configuration remains manual-sync. A runner label is not a security boundary; repository workflows that target it can use its limited read access.

## What is not implemented or proven

- **Observed in PR #38:** Codex added a small unused internal health helper and regression test, passed 85 local tests and PR CI, merged itself, monitored GitHub Actions while active, and recorded successful digest-matched ARC verification on the original PR. This proves a trivial autonomous pipeline handshake, **not** complex feature correctness or CI failure repair. Source commit `9f147f5eab71e36f48b4c99937d899125622ed08`; published digest `sha256:1c704ea1ae989795866fe6bad28ec0e111fa00424f3c11b36f3ad79e445b763d`; run: https://github.com/bturetzky/chatgpt-discord-bot/actions/runs/42538409045.
- The verifier checks Kubernetes rollout state, **not** Discord connectivity, tool behavior, or live chat responses. A human dev Discord smoke test remains useful before production.
- The current verifier times out on a digest mismatch; it does not reliably classify superseded runs. Workflow concurrency cancels older verification jobs, but that is not a general-purpose supersession protocol.
- No durable event-driven agent resumption, external orchestrator, automatic CI-to-Codex callback, or autonomous production release has been configured. If Codex stops after creating a PR, resume it manually.
- No inbound GitHub webhook to the private homelab is desired.

## First experiment outcome and next step

The first experiment was an internal health helper with no Discord-visible behavior (PR #38). Codex kept its session running and polled the workflow to completion, then posted evidence back to the PR. It did **not** wake from a paused session on a deployment event. Next: try a narrow user-facing feature from an approved design, with deterministic tests and a human dev Discord smoke test; continue allowing automatic dev merges only within agreed scope. Evaluate event-driven resumption later if long waits, session costs, or session lifetime become an actual problem.

Keep feature-specific implementation details in their design docs. See [deployment workflow](deployment-workflow.md), [engineering roadmap](engineering-roadmap.md), and the existing server-awareness, rich-content, and proactive-personality designs.
