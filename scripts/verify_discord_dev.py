#!/usr/bin/env python3
"""Verify the expected Discord dev image is healthy using in-cluster read-only API."""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

API = "https://kubernetes.default.svc"
CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"
IMAGE = "ghcr.io/bturetzky/chatgpt-discord-bot@"
EXPECTED = os.environ["EXPECTED_DIGEST"]
if not EXPECTED.startswith("sha256:") or len(EXPECTED) != 71 or any(c not in "0123456789abcdef" for c in EXPECTED[7:]):
    sys.exit("Invalid expected digest")

def get(path):
    with open(TOKEN, encoding="utf-8") as f:
        token = f.read().strip()
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=CA), timeout=10) as resp:
        return json.load(resp)

deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    try:
        app = get("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/discord-dev")
        deployment = get("/apis/apps/v1/namespaces/discord-dev/deployments/chatgpt-discord-bot")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"Unable to inspect rollout: {exc}", flush=True)
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
    if image == IMAGE + EXPECTED and sync == "Synced" and health == "Healthy" and observed >= generation and ready >= replicas and updated >= replicas:
        print("PASS: expected digest deployed and healthy")
        sys.exit(0)
    # Do not declare superseded solely from an old healthy Deployment:
    # Argo may not have observed the new GitOps commit yet.
    time.sleep(10)
sys.exit("TIMEOUT: expected digest did not become healthy within 10 minutes")
