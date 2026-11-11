# CI/CD, deployment and promotion

The application repo owns workflows and code; [homelab-gitops](https://github.com/bturetzky/homelab-gitops) is authoritative for Kubernetes, Argo CD, Secrets, PVCs, runner RBAC and pinned image digests. Dev and prod have separate Discord applications, credentials, servers and SQLite volumes.

## Implemented release flow

1. **Application PR:** `make test` and Docker build checks; no image publishing or production changes.
2. **Merge to `main`:** [docker-build.yml](../.github/workflows/docker-build.yml) publishes a GHCR image with commit identity and updates the **dev** GitOps digest via a GitHub App PR that is automatically merged.
3. **Dev rollout:** Argo CD reconciles through polling (no inbound webhook). `verify-dev` runs on an ephemeral ARC runner and checks expected digest, Argo CD Synced/Healthy, updated/ready replicas, gateway startup marker, stable pod and zero restarts. The verifier has narrowly scoped read-only Kubernetes access; it cannot read Secrets or change resources.
4. **Human acceptance:** exercise the changed behavior in the dev Discord server. Passing CI, deployment verification and a gateway marker do **not** establish user-visible correctness.
5. **Manual production promotion:** run [promote-prod.yml](../.github/workflows/promote-prod.yml) via **Actions → Promote Discord bot to production → Run workflow** on `main`. It reads the dev-pinned digest and opens a **review-only** GitOps PR for production. Review and merge that PR; the workflow does not rebuild, auto-merge or deploy production imperatively.
6. **Production verification:** confirm Argo CD sync/health, Deployment rollout, exact image digest, startup logs and an actual Discord response.

The operator has verified the end-to-end CI→dev→manual prod workflow. The ARC rollout check is infrastructure evidence, not a live Discord feature test. No autonomous production release is allowed.

## Commands

```bash
make test
kubectl -n discord-dev rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl -n discord-dev get pods -l app=chatgpt-discord-bot
kubectl -n discord-dev logs deployment/chatgpt-discord-bot --since=10m
```

For smoke prompts and feature-specific checks, see [operations](operations.md). Inspect the GitOps manifest and Deployment selector rather than assuming an old tag or label remains current.

## Rollback and safety

Revert the production image promotion commit/PR in GitOps, let Argo CD reconcile and verify bot behavior. Image rollback does **not** undo SQLite schema migrations, external Pinecone writes or other side effects; review compatibility before promoting stateful changes. Never use `kubectl set image` as a substitute for GitOps. Keep production approval manual. Do not expose secrets, guild IDs, messages or memory records in CI logs or PRs.

A single-instance Discord gateway bot may briefly overlap connections during rolling updates; assess `Recreate` only if observed side effects justify downtime. Do not confuse future improvements with requirements for the existing release workflow.
