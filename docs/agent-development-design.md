# Autonomous feature development — design and decisions

**Status:** Proposed architecture; decisions below agreed 2026-11-07. **Not implemented.**

## Goal

Enable a cloud-hosted coding agent to implement substantial Discord bot features, test and repair them, automatically merge/deploy to the isolated dev environment, and pause at meaningful human checkpoints. Preserve the existing deliberate production promotion workflow.

## Confirmed decisions

- **Execution:** Cloud-hosted development agent; homelab hardware is not intended to host the LLM/agent itself.
- **Development autonomy:** Agent may implement features, update tests/docs, open PRs, inspect CI, repair failures, and automatically merge its own application PRs into `main` after required checks pass. Dev is a disposable/testing environment for the operator and bot. Automatic merge is **permission to deploy to dev**, not to production.
- **Existing deployment path stays:** Application `main` builds an immutable image, automatically updates the dev image in `bturetzky/homelab-gitops`, and Argo CD deploys `discord-dev`. Production promotion remains a separate, **manual, reviewed GitOps PR**, using the tested digest; never auto-promote.
- **GitOps authority:** `bturetzky/homelab-gitops` is authoritative for cluster manifests and desired state. Avoid direct imperative image changes.
- **Human approval gates:** Significant architecture decisions, new infrastructure or credentials, destructive changes, historical backfills, and enabling persistent memory writes require approval. Production promotion always requires approval.
- **Agent limits:** Bound retries, time and spend; escalate repeated failures rather than looping indefinitely. Keep credentials narrowly scoped; do not expose production bot secrets to agent jobs.
- **Documentation:** Keep feature design decisions and validation evidence near their respective feature docs; use this file for cross-feature agent architecture. Distinguish confirmed decisions, proposals, and observed implementation. Avoid a parallel task-manager checklist.

## Further decisions (2026-11-07)

- **Concurrency:** Start with exactly one feature-development agent at a time, with exclusive use of the shared dev environment for integration validation. Revisit parallel development only after the single-agent lifecycle is reliable.
- **Orchestration preference:** Prefer an existing managed cloud platform over building and maintaining a bespoke orchestrator, provided it supports durable sessions, external CI/deployment callbacks, approval gates, and bounded retries. Evaluate Codex Cloud and the OpenAI Agents API; **no platform selected yet**.

## Platform investigation (2026-11-07; research, not implementation)

- **Codex Cloud:** Included in eligible ChatGPT Plus usage limits, with optional paid credits; no separate standard cloud VM fee at this time. Best low-cost initial experiment. Ordinary Codex Cloud tasks should **not** be assumed to automatically resume on arbitrary GitHub or homelab deployment events.
- **Agents API (public beta):** OpenAI-managed Codex harness, durable sessions, hosted sandboxes, asynchronous turns, session webhooks, recovery, and one-time/periodic scheduled automations. Supports resuming the same session; managed agent execution does not automatically connect GitHub workflow completion to the correct feature session. A thin event adapter or scheduled polling is still needed.
- **Agents API billing:** Separate from ChatGPT subscription: model tokens, tools and hosted sandbox compute. As checked 2026-11-07, GPT-6.1 Sol standard API rates are $2/1M input, $0.10/1M cached input, $10/1M output; GPT-6.1 Terra $1/$0.05/$5. Cache-write charges can also apply. Standard hosted container price examples: 1 GiB $0.03, 4 GiB $0.12 per 20-minute session; verify billing at implementation time. Budget and usage tracing required.
- **Platform recommendation:** Try Codex Cloud on a contained feature first to measure capability and subscription consumption; evaluate Agents API for event-driven end-to-end automation, likely with a minimal GitHub-event bridge and a least-privilege homelab verification runner. **No platform committed yet.**
- **Sources:** [Codex pricing](https://learn.chatgpt.com/docs/pricing), [Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview), [Agents API session webhooks](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks), [Agents API scheduled automations](https://developers.openai.com/api/docs/guides/agents-api/sessions/automations), [API pricing](https://developers.openai.com/api/docs/pricing).

## Proposed integration architecture (not yet selected or implemented)

- **GitHub Actions feedback:** Agent reads workflow runs, check results, and failed job logs via GitHub API.
- **Homelab verification:** Prefer a tightly scoped, outbound-only, ephemeral self-hosted GitHub Actions runner to verify Argo CD sync, expected image digest, Kubernetes rollout/health, bot startup, and approved dev integration tests. Publish logs/results as GitHub Actions artifacts. No public Kubernetes API or broad cluster-admin access.
- **Security:** Trusted verification workflows, isolated runner, least-privilege read-only access to dev resources, narrowly approved test execution. Do not execute arbitrary unreviewed PR code with cluster credentials.
- **Deployment identity:** Correlate reports to exact application commit, image digest, GitOps commit, environment and timestamps; stale healthy reports must never satisfy a new deployment.
- **Alternative/complement:** Extend the existing `homelab-observed-state` outbound publishing pattern if continuous deployment telemetry is needed independently of GitHub Actions.
- **Integration limitations:** Kubernetes readiness does not prove Discord behavior. Use deterministic fixtures and approved dev-only interaction tests; social appropriateness of proactive reactions may still require human evaluation.

## Proposed durable execution lifecycle (to refine)

1. Agent works on a feature branch, runs local tests, opens PR.
2. GitHub Actions runs CI; agent consumes results and repairs failures with bounded retries.
3. After required checks pass, agent merges to application `main`; existing workflow publishes image and updates dev GitOps.
4. Verification workflow waits for the *matching digest* to become healthy in dev, with timeout and diagnostics; then executes dev integration tests.
5. Agent consumes the verification result and either fixes/repeats or marks a feature ready for human review.
6. Human explicitly initiates and reviews production promotion.

**Unresolved orchestration design:** Choose how agent sessions are launched and resumed on GitHub events (e.g. external cloud agent service, webhook-driven orchestrator, or GitHub workflow dispatch), how durable run state is represented, and how budget/checkpoint policies are enforced. A CI workflow waiting on a rollout is not itself a continuously running agent.

## Open design questions

- Can a managed platform (particularly the Agents API) provide durable execution and event-driven resumption without a custom orchestration service? Validate the concrete API and GitHub/homelab integration first.
- Should verification use a self-hosted GitHub Actions runner, an outbound-reporting observer, or both?
- What exact dev smoke-test mechanism can exercise Discord interactions safely?
- What retry, runtime, and cost budgets are appropriate?
- Which architecture changes can be pre-approved in a feature design before autonomous implementation?

## Related documents

- [Deployment workflow](deployment-workflow.md)
- [Engineering roadmap](engineering-roadmap.md)
- [Server awareness design](server-awareness-design.md)
- [Rich content understanding design](rich-content-understanding-design.md)
- [Proactive personality design](proactive-personality-design.md)
