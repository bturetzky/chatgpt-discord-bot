# Development bot smoke test

Run after a dev rollout, before invoking the **manual** production promotion workflow. The Docker build already runs deterministic unit/component tests; these checks exercise real Discord and external services.

## 1. Deployment health

```bash
kubectl -n discord-dev rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl -n discord-dev get pods -l app=chatgpt-discord-bot
kubectl -n discord-dev logs deployment/chatgpt-discord-bot --since=10m
```

If the label selector differs, inspect the Deployment's selector with `kubectl -n discord-dev get deployment chatgpt-discord-bot -o yaml`. Check for import errors, crash loops, authentication failures, and repeated exceptions. Kubernetes readiness alone does **not** establish Discord connectivity.

## 2. Dev Discord smoke checks

Use the **development** Discord application/server, not production. Send separate messages so tool failures can be isolated:

| Check | Prompt | Expected |
| --- | --- | --- |
| Basic response | `@chatgpt-dev What's 17 × 23? Answer briefly.` | `391` |
| Weather | `@chatgpt-dev What's today's forecast for Gig Harbor, WA? Please use your weather tool.` | Current forecast, or an explicit provider error; no crash |
| Search | `@chatgpt-dev Search the web for the official Python documentation URL.` | URL with a successful search, or an explicit DDG error (HTTP 202 rate limiting has been observed) |
| Webpage fetch | `@chatgpt-dev Fetch https://docs.python.org/3/ and summarize what the page contains.` | Specific documentation topics, or explicit fetch error |
| Memory retrieval | `@chatgpt-dev Tell me one thing you remember about me. Don't invent anything if nothing is found.` | A previously known fact, or an honest no-memory answer; confirm retrieval in logs if needed |

Do not use the memory **write** tool for routine smoke testing: it persists records in the shared Pinecone index. Existing memory is intentionally shared between the trusted server and DMs; these checks do not validate isolation.

## 3. Restart / lifecycle check (optional after lifecycle changes)

```bash
kubectl -n discord-dev rollout restart deployment/chatgpt-discord-bot
kubectl -n discord-dev rollout status deployment/chatgpt-discord-bot --timeout=120s
kubectl -n discord-dev logs deployment/chatgpt-discord-bot --since=10m
```

Send one more basic Discord prompt. Inspect termination/startup logs for errors. A successful rollout alone does not prove graceful shutdown; inspect previous container logs when available.

## 4. Promote only after dev checks

Use **Actions → Promote Discord bot to production → Run workflow** on main. Review the resulting `homelab-gitops` production PR and merge manually. The workflow promotes the **already tested dev digest**, not a rebuilt image. Verify the production rollout and bot responsiveness afterward.

Failures should be recorded with the failing step, timestamp, and sanitized error message; never paste credentials, full user conversations, or raw Pinecone memory into an issue.
