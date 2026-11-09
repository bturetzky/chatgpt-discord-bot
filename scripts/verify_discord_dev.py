#!/usr/bin/env python3
"""Verify the expected Discord dev image is healthy using in-cluster read-only API."""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

API = "https://kubernetes.default.svc"
CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"
IMAGE = "ghcr.io/bturetzky/chatgpt-discord-bot@"
EXPECTED = os.environ["EXPECTED_DIGEST"]
if not EXPECTED.startswith("sha256:") or len(EXPECTED) != 71 or any(c not in "0123456789abcdef" for c in EXPECTED[7:]):
    sys.exit("Invalid expected digest")

def get(path, raw=False):
    with open(TOKEN, encoding="utf-8") as f:
        token = f.read().strip()
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=CA), timeout=10) as resp:
        return resp.read().decode('utf-8', errors='replace') if raw else json.load(resp)

def pod_summary(pods):
    """Only Kubernetes status metadata; never log bodies or secrets."""
    result = []
    for pod in pods[:5]:
        meta = pod.get("metadata", {})
        status = pod.get("status", {})
        entries = [s for s in status.get("containerStatuses", []) if s.get("name") == "chatgpt-discord-bot"]
        if not entries:
            result.append(f"{meta.get('name', 'unknown')}: phase={status.get('phase', 'unknown')} status=missing")
            continue
        s = entries[0]
        state = s.get("state", {})
        waiting = state.get("waiting", {})
        terminated = state.get("terminated", {})
        last = s.get("lastState", {}).get("terminated", {})
        reason = waiting.get("reason") or terminated.get("reason") or last.get("reason") or "Running"
        exit_code = terminated.get("exitCode", last.get("exitCode", "n/a"))
        result.append(f"{meta.get('name', 'unknown')}: phase={status.get('phase', 'unknown')} ready={s.get('ready')} restarts={s.get('restartCount', 0)} reason={reason} exit_code={exit_code}")
    return "; ".join(result) or "no matching pods"


last_failure = "no observations"
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    try:
        app = get("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/discord-dev")
        deployment = get("/apis/apps/v1/namespaces/discord-dev/deployments/chatgpt-discord-bot")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        last_failure = f"api_error: {type(exc).__name__}"
        print(last_failure, flush=True)
        time.sleep(10)
        continue
    status = app.get("status", {})
    sync = status.get("sync", {}).get("status", "Unknown")
    health = status.get("health", {}).get("status", "Unknown")
    metadata = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    state = deployment.get("status", {})
    containers = spec.get("template", {}).get("spec", {}).get("containers", [])
    images = [c.get("image") for c in containers if c.get("name") == "chatgpt-discord-bot"]
    image = images[0] if len(images) == 1 else None
    generation = metadata.get("generation", 0)
    observed = state.get("observedGeneration", 0)
    replicas = spec.get("replicas", 1)
    ready = state.get("readyReplicas", 0)
    updated = state.get("updatedReplicas", 0)
    print(f"image={image} sync={sync} health={health} generation={observed}/{generation} ready={ready}/{replicas} updated={updated}/{replicas}", flush=True)
    last_failure = f"rollout_pending: sync={sync} health={health} image_match={image == IMAGE + EXPECTED} generation={observed}/{generation} ready={ready}/{replicas} updated={updated}/{replicas}"
    if image == IMAGE + EXPECTED and sync == "Synced" and health == "Healthy" and observed >= generation and ready >= replicas and updated >= replicas:

        # Inspect only the newly deployed, ready dev pod. Never print pod logs.
        try:
            pods = get("/api/v1/namespaces/discord-dev/pods?labelSelector=app%3Dchatgpt-discord-bot").get("items", [])
            candidates = []
            for pod in pods:
                name = pod.get("metadata", {}).get("name", "")
                statuses = [s for s in pod.get("status", {}).get("containerStatuses", [])
                            if s.get("name") == "chatgpt-discord-bot"]
                if (not name.startswith("chatgpt-discord-bot-") or
                        pod.get("metadata", {}).get("deletionTimestamp") or len(statuses) != 1):
                    continue
                container = statuses[0]
                if container.get("image") == IMAGE + EXPECTED and container.get("ready"):
                    candidates.append((name, container.get("restartCount", 0)))
            if len(candidates) != 1:
                last_failure = "pod_not_ready: " + pod_summary(pods)
                print("Runtime: " + last_failure, flush=True)
                time.sleep(10)
                continue
            pod_name, restarts = candidates[0]
            if restarts:
                last_failure = f"pod_restarted: {pod_name} restarts={restarts}; " + pod_summary(pods)
                print("Runtime: " + last_failure, flush=True)
                time.sleep(10)
                continue
            log_path = ("/api/v1/namespaces/discord-dev/pods/" +
                        urllib.parse.quote(pod_name, safe="") +
                        "/log?container=chatgpt-discord-bot&tailLines=2000")
            logs = get(log_path, raw=True)
            if ("Discord gateway ready: bot_id=" not in logs and
                    "Discord gateway session resumed" not in logs):
                last_failure = "gateway_not_confirmed: no ready/resumed marker; " + pod_summary(pods)
                print("Runtime: " + last_failure, flush=True)
                time.sleep(10)
                continue
            time.sleep(20)
            current = get("/api/v1/namespaces/discord-dev/pods?labelSelector=app%3Dchatgpt-discord-bot").get("items", [])
            stable = any(
                p.get("metadata", {}).get("name") == pod_name and
                any(s.get("name") == "chatgpt-discord-bot" and s.get("ready") and
                    s.get("restartCount", 0) == 0 and s.get("image") == IMAGE + EXPECTED
                    for s in p.get("status", {}).get("containerStatuses", []))
                for p in current
            )
            if stable:
                print(f"PASS: digest deployed, Argo healthy, Discord gateway established, pod {pod_name} stable with zero restarts", flush=True)
                sys.exit(0)
            last_failure = "pod_unstable: " + pod_summary(current)
            print("Runtime: " + last_failure, flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_failure = f"runtime_api_error: {type(exc).__name__}"
            print("Runtime: " + last_failure, flush=True)
        time.sleep(10)
    # Do not declare superseded solely from an old healthy Deployment:
    # Argo may not have observed the new GitOps commit yet.
    time.sleep(10)
print(f"FAIL: verification timed out after 600s; expected_digest={EXPECTED}; last_failure={last_failure}", flush=True)
sys.exit(1)
