# Autonomous feature development — design and decisions

**Status (2026-11-08):** Initial Codex Cloud experiment approved; GitHub CI, automated dev deployment, and ARC rollout verification implemented and operator-verified. Autonomous Codex implementation/CI-repair/merge lifecycle **not yet exercised end-to-end**.

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

- The **first autonomous Codex feature lifecycle** (implement → test → PR → fix CI → merge → inspect rollout) has not yet been observed.
- The verifier checks Kubernetes rollout state, **not** Discord connectivity, tool behavior, or live chat responses. A human dev Discord smoke test remains useful before production.
- The current verifier times out on a digest mismatch; it does not reliably classify superseded runs. Workflow concurrency cancels older verification jobs, but that is not a general-purpose supersession protocol.
- No durable event-driven agent resumption, external orchestrator, automatic CI-to-Codex callback, or autonomous production release has been configured. If Codex stops after creating a PR, resume it manually.
- No inbound GitHub webhook to the private homelab is desired.

## First experiment procedure

Provide Codex one already-agreed, contained feature design. Let it inspect code, implement tests/docs, and open a PR. Permit merge to application `main` only after checks pass and within the agreed scope. Inspect the `verify-dev` GitHub Actions job for the matching digest; then manually exercise the changed behavior in the dev Discord server. Review agent output, fixes, cost/time, and missing capabilities before considering broader autonomy.

Keep feature-specific implementation details in their design docs. See [deployment workflow](deployment-workflow.md), [engineering roadmap](engineering-roadmap.md), and the existing server-awareness, rich-content, and proactive-personality designs.
