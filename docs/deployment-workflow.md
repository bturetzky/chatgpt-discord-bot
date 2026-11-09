# Discord bot CI/CD and promotion design

**Status:** CI/CD, automated dev deployment, and manual production promotion implemented and exercised successfully.  
**Verified:** 2026-11-08 (including automated ARC dev rollout verification)  
**Repositories:** [chatgpt-discord-bot](https://github.com/bturetzky/chatgpt-discord-bot) and [homelab-gitops](https://github.com/bturetzky/homelab-gitops)

## Automated post-deployment verification (2026-11-08)

- After the main-branch build and automatically merged dev GitOps update, the `verify-dev` job in `docker-build.yml` runs on the ephemeral in-cluster `discord-dev-verify` ARC runner.
- `scripts/verify_discord_dev.py` uses a dedicated read-only Kubernetes ServiceAccount to inspect the named dev Deployment, Argo CD Application, and dev pod status/startup logs. It waits up to 10 minutes for the expected digest, Argo CD Synced/Healthy, and ready/updated replicas; it also checks for a Discord gateway ready/resumed startup marker, zero container restarts, and a 20-second stable readiness window. GitHub job timeout is 12 minutes.
- The operator confirmed the first end-to-end job **passed** on 2026-11-08. Argo CD uses ordinary Git polling; no inbound webhook is configured. Refresh latency can consume part of the timeout.
- The first rollout-only verifier passed in PR #38. Runtime gateway verification was added in PR #39 and subsequently passed live in the PR #40 rollout (2026-11-08/09). PR #40 also added sanitized failure diagnostics and corrected the pod image check to compare the pod spec image, not the container runtime image identifier. The operator observed PASS: expected digest, Argo Synced/Healthy, Discord gateway startup marker, stable ready pod, zero restarts. A gateway startup marker is **not** a continuous Discord connection check or a real-message functional test. This proves image rollout health and evidence of gateway startup, **not** live Discord feature behavior. Manual dev chat/tool smoke testing is still required for behavior changes and before production promotion. Mismatched/superseded digests currently time out rather than receiving a distinct superseded result.
- ARC Helm, ServiceAccount, and narrowly scoped RBAC are owned by the existing `arc-discord-dev-runners` Application in `homelab-gitops` (manual sync). The verifier now has namespace-scoped `list` on dev pods and `get` on dev pod logs, plus the original named-resource reads; no secrets, exec, or writes. Argo CD reconciliation was changed in GitOps to 60s plus 15s jitter (operator reports merge and manual sync). The ARC Application returned to Synced/Healthy after an orphaned Helm-generated `discord-dev-verify-gha-rs-no-permission` ServiceAccount was deleted; its stranded `actions.github.com/cleanup-protection` finalizer was manually cleared after checking that the active runner uses `discord-dev-verifier` and that the orphan had no owner references. `Prune=false` remains unchanged. No separate verification service or Application.

## Verified implementation and production promotions

- PR checks run the complete unittest suite and Docker build without publishing; main builds publish a SHA-tagged GHCR image and update dev GitOps to the published immutable digest through a GitHub App-created, automatically merged PR.
- The standalone suite uses Python 3.12 and Poetry 1.8.3 to install the locked main dependencies (`poetry install --only main --no-root --no-interaction`), then runs `poetry run python -m unittest discover -s tests -t .`. It needs the full application dependencies, not just the OpenAI SDK; external services are mocked. The Docker build separately runs the suite on Python 3.12.
- Dev Argo CD rollout and Discord conversation/weather behavior were verified. The Responses API serialization bug was corrected in PR #11.
- Manual promotion workflow [`promote-prod.yml`](../.github/workflows/promote-prod.yml) was implemented in PR #12. It reads the digest currently pinned in dev GitOps and opens a **review-only** production GitOps PR; it never rebuilds or auto-merges.
- **First production promotion confirmed by user:** workflow run against main; resulting GitOps PR reviewed and merged; dev/prod digests matched; production rollout occurred; production Discord bot remained responsive.
- **Latest checkpoint (2026-11-07):** operator confirmed the PR #27 unused-dependency cleanup was merged and promoted to production after a green Docker build. Post-promotion live smoke-test details were not separately reported.
- **To promote again:** verify dev, run **Actions → Promote Discord bot to production → Run workflow** on main, review and merge the GitOps production PR, verify Argo CD rollout and live bot response. If prod already pins the same digest, no PR is opened.
- **Rollback:** revert the production promotion commit in GitOps and verify the resulting rollout. Data/external side effects may not roll back with the image.

## Goal

Make bot changes safely and repeatably: validate pull requests, publish one immutable image per successful main-branch build, deploy automatically to development, test against the isolated development Discord server, and explicitly promote **the same tested image** to production via a GitOps pull request. Keep the workflow simple and auditable, without introducing a separate develop branch or Argo CD Image Updater.

## Environment and configuration

- Dev and production use distinct Discord applications, tokens and servers; both are Argo CD-managed.
- The GitOps deployment manifests in `apps/discord/dev/deployment.yaml` and `apps/discord/prod/deployment.yaml` are authoritative for the currently pinned digests. Do not rely on historical image tags recorded in older documentation.
- [`docker-build.yml`](../.github/workflows/docker-build.yml) implements CI, image publishing, automatic dev GitOps updates, and post-deployment ARC verification. [`promote-prod.yml`](../.github/workflows/promote-prod.yml) implements manual production promotion.
- Existing GitHub App credentials are used for cross-repository GitOps PR creation; production PR merging remains a human action.

## Desired flow

1. **Feature branch / PR in application repo:** run automated tests and validate Docker build; **do not publish** images or change GitOps.
2. **Merge to main:** after successful checks, build and push an immutable image to GHCR, identified by source commit SHA (e.g. `sha-a83f219`). Prefer deploying by registry digest (`@sha256:...`) to eliminate mutable-tag ambiguity.
3. **Development rollout:** CI opens a PR in `homelab-gitops` updating only the dev image reference. The GitHub App immediately squash-merges the PR without GitHub's plan-restricted native auto-merge feature; Argo CD detects the manifest change and rolls out the image. Verify actual deployed image/digest and rollout health. The ARC job automatically verifies the image digest and Kubernetes rollout; live Discord behavior testing remains manual.
4. **Promotion:** after successful dev testing, manually invoke a workflow selecting the **already-built, tested image digest**. It opens a `homelab-gitops` PR changing only the production image reference. Review and merge to authorize release; Argo CD deploys it. Do not rebuild during promotion.
5. **Rollback:** revert the production promotion commit/PR in GitOps; Argo CD restores the previous known image reference. Verify rollout and bot functionality.

## Design decisions and implementation considerations

- **GitOps remains authoritative** for desired image versions. Avoid `kubectl set image` or any automation that changes live Deployment images outside Git.
- **No new long-lived develop branch** required. Development is the automatic deployment environment for successful main builds.
- **No Argo CD Image Updater initially.** Application GitHub Actions already knows which artifact passed CI and can propose the GitOps update.
- **Credentials:** the application repository's default `GITHUB_TOKEN` does not automatically have write access to the private GitOps repository. Prefer a narrowly scoped GitHub App installation token or fine-grained credential with only necessary repo permissions. Never store Discord tokens in Git or pass them to untrusted PR jobs.
- **Cross-repository PR automation:** ensure branch creation, PR permissions, validation, and auto-merge policy are explicitly configured. Keep production PR merges manual.
- **Image identity:** use commit SHA tags for human-readable traceability and immutable digest references in manifests where practical. Record the source commit/digest in PR descriptions. Prevent release tags from overwriting shared mutable `latest`.
- **Testing:** inspect the existing tests, establish a reliable baseline, add a required test job, and run a Docker build check on PRs. Do not gate deployment on tests until their reliability is verified.
- **Rollout semantics:** `imagePullPolicy: Always` does not trigger restarts when `latest` changes. A GitOps manifest change to a unique image ref triggers a rollout.
- **Discord connection safety:** consider `Recreate` instead of RollingUpdate for the single-instance gateway bot to avoid brief overlap of old/new bot connections. Evaluate downtime tradeoff and confirm no duplicate side effects.
- **Operational verification:** check Argo CD sync/health, Deployment rollout status, container image digest, bot startup logs, and a real dev Discord interaction before promotion. A healthy Kubernetes Deployment alone does not prove the bot is functioning.
- **Rollback limitations:** image rollback alone may not reverse incompatible data/schema changes or external side effects; review such changes separately.

## Related technical debt (separate from the initial CI/CD implementation)

- Update deprecated/old GitHub Actions versions.
- Improve Docker layer caching and pin build tooling/dependencies appropriately.
- Python 3.12 runtime migration is complete and promoted; assess future Python 3.14 compatibility only after dependency updates.
- Reconcile application version metadata (`0.2.0`) with published image versioning (`1.0.4`); decide whether semantic release tags are needed alongside SHA images.
- OpenAI SDK and Responses API modernization completed; continue expanding integration tests.
- Assess test quality/coverage and add meaningful bot behavior tests.

## Original rollout sequence (completed for core CI/CD)

1. Make CI safe: PRs test/build but do not push; update GitHub Actions; introduce immutable SHA images.
2. Switch dev/prod GitOps image references away from mutable tags (preserve existing working production version until intentionally promoted).
3. Automate successful main builds proposing dev GitOps updates; immediately merge dev-only PRs through the GitHub App (no paid native auto-merge needed).
4. Add manual production promotion workflow that proposes a GitOps PR for the exact tested digest.
5. Document verification and rollback, then consider separate runtime/SDK modernization work.

## Open questions

- Resolved: GitHub App credentials used for cross-repository GitOps PRs.
- Resolved: dev GitOps PRs should merge automatically without a manual review step.
- What test command and smoke checks are reliable enough to gate builds and promotion?
- Should `Recreate` replace RollingUpdate for both bot Deployments?
- Do we want explicit semantic version tags/releases, or only commit-SHA identities?

**Important:** The workflow is implemented and the first production promotion was confirmed by the user. Actual live Kubernetes configuration and deployment status remain authoritative in `homelab-gitops`.
