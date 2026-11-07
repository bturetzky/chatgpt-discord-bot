# Discord bot CI/CD and promotion design

**Status:** CI build/publish and first dev GitOps rollout verified; automated dev deployment proposed in PR #8  
**Discussed:** 2026-11-06  
**Repositories:** [chatgpt-discord-bot](https://github.com/bturetzky/chatgpt-discord-bot) (application and CI) and [homelab-gitops](https://github.com/bturetzky/homelab-gitops) (deployment manifests and Argo CD)

## Implementation status (2026-11-06)

- **Verified:** PR builds do not publish images; successful main builds publish a `sha-<commit>` GHCR image. The `sha-549aad6` image was deployed to `discord-dev` through GitOps; Argo CD was Synced/Healthy and Kubernetes rollout succeeded.
- **Known application limitation:** the dev bot connects to Discord but OpenAI rejects legacy `function` role messages with the configured model. Application compatibility remains separate technical debt; production remains unchanged.
- **Proposed in this PR:** after publishing on main, the bot workflow opens a dev-only GitOps PR pinned to the exact published **image digest** and immediately squash-merges the resulting PR with the GitHub App token. Version-tag builds and PR builds do not deploy.
- **Prerequisites before merge:** create a GitHub App installed on `homelab-gitops` with repository **Contents: Read and write** and **Pull requests: Read and write**; configure bot repository variable `GITOPS_APP_ID` and Actions secret `GITOPS_APP_PRIVATE_KEY`. GitOps must permit squash merging and the App must be allowed to merge PRs. GitHub Free does not offer native auto-merge for private repos, so CI calls `gh pr merge --squash` directly (no `--auto`). Standard merge restrictions are enforced; checks that are not required may still be pending. Do not use branch protection bypass.
- **Validation:** merge a bot PR, check the `deploy-dev` job and GitOps PR, then confirm Argo CD and the dev pod use the expected digest. If required checks or reviews are not satisfied, the direct merge fails, leaving the PR open and failing the workflow. A new workflow will not deploy merely by merging this CI PR unless its resulting main push publishes a new image.
- **Production promotion:** still manual and not yet implemented.

## Goal

Make bot changes safely and repeatably: validate pull requests, publish one immutable image per successful main-branch build, deploy automatically to development, test against the isolated development Discord server, and explicitly promote **the same tested image** to production via a GitOps pull request. Keep the workflow simple and auditable, without introducing a separate develop branch or Argo CD Image Updater.

## Confirmed environment (2026-11-06)

- `discord-dev` and `discord-prod` use **different Discord applications/bots, tokens, and servers**. Development testing is isolated from production.
- Both Kubernetes workloads are Argo CD Applications tracking `homelab-gitops/main`, with automated sync and self-healing.
- Dev manifest: [apps/discord/dev/deployment.yaml](https://github.com/bturetzky/homelab-gitops/blob/main/apps/discord/dev/deployment.yaml) uses `ghcr.io/bturetzky/chatgpt-discord-bot:latest` and `imagePullPolicy: Always`.
- Prod manifest: [apps/discord/prod/deployment.yaml](https://github.com/bturetzky/homelab-gitops/blob/main/apps/discord/prod/deployment.yaml) uses `:1.0.4` and `imagePullPolicy: IfNotPresent`.
- Both Deployments are single-replica and currently use a RollingUpdate strategy.
- Application workflow: [.github/workflows/docker-build.yml](../.github/workflows/docker-build.yml) triggers on PRs to main, pushes to main, and `v*` tags. It uses older checkout/login/build-push actions, publishes on every event (including PRs), and publishes `latest` for non-version-tag events.
- A test file exists at `tests/test_chat_bot.py`, but the image workflow does not run tests.
- The Dockerfile uses `python:3.10-slim`; `pyproject.toml` reports app version `0.2.0`, and pins the OpenAI Python library to `0.28`.

## Desired flow

1. **Feature branch / PR in application repo:** run automated tests and validate Docker build; **do not publish** images or change GitOps.
2. **Merge to main:** after successful checks, build and push an immutable image to GHCR, identified by source commit SHA (e.g. `sha-a83f219`). Prefer deploying by registry digest (`@sha256:...`) to eliminate mutable-tag ambiguity.
3. **Development rollout:** CI opens a PR in `homelab-gitops` updating only the dev image reference. The GitHub App immediately squash-merges the PR without GitHub's plan-restricted native auto-merge feature; Argo CD detects the manifest change and rolls out the image. Verify actual deployed image/digest and rollout health. Dev testing against its isolated Discord server remains manual.
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
- Evaluate moving from Python 3.10 to a newer supported version, with compatibility testing.
- Reconcile application version metadata (`0.2.0`) with published image versioning (`1.0.4`); decide whether semantic release tags are needed alongside SHA images.
- Modernize the legacy OpenAI Python SDK (`0.28`) as a separate application change.
- Assess test quality/coverage and add meaningful bot behavior tests.

## Suggested incremental rollout (planned, not completed)

1. Make CI safe: PRs test/build but do not push; update GitHub Actions; introduce immutable SHA images.
2. Switch dev/prod GitOps image references away from mutable tags (preserve existing working production version until intentionally promoted).
3. Automate successful main builds proposing dev GitOps updates; immediately merge dev-only PRs through the GitHub App (no paid native auto-merge needed).
4. Add manual production promotion workflow that proposes a GitOps PR for the exact tested digest.
5. Document verification and rollback, then consider separate runtime/SDK modernization work.

## Open questions

- Which GitHub authentication approach should CI use for cross-repository PR creation (GitHub App preferred vs fine-grained token)?
- Resolved: dev GitOps PRs should merge automatically without a manual review step.
- What test command and smoke checks are reliable enough to gate builds and promotion?
- Should `Recreate` replace RollingUpdate for both bot Deployments?
- Do we want explicit semantic version tags/releases, or only commit-SHA identities?

**Important:** This page records the agreed direction and observed repository state, not completed implementation. Actual Kubernetes configuration and deployment status are authoritative in `homelab-gitops`.
