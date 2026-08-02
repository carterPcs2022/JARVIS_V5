"""services/webhooks.py — Webhook receiver for GitHub and Stripe.

Every source that reaches WebhookManager.process() is verified against that
service's own documented signing scheme before this module ever sees the
payload (see verify_webhook_source, called from server/routes/final_features.py
before the request body is parsed). Sources with no registered handler AND no
known signing scheme (the old "IFTTT, Zapier, or anything else" catch-all)
are rejected at the route with a 404 — that catch-all used to hand any
anonymous POST body straight to custom_handler(), which fed it into
brain.process_dict() with zero auth. There was no evidence any such
integration was actually wired up (no IFTTT/Zapier config anywhere in this
codebase), so closing it costs nothing real and removes a live
prompt-injection surface."""
import hashlib
import hmac
import time
from datetime import datetime

from fastapi import HTTPException


def verify_webhook_source(source: str, request, raw_body: bytes):
    """Raise HTTPException if `source` isn't github/stripe, or the request's
    signature doesn't verify. Fails closed: an unset secret rejects every
    request for that source rather than accepting anything, same convention
    as verify_twilio_signature in utils/security.py."""
    if source == "github":
        from config.settings import GITHUB_WEBHOOK_SECRET
        _verify_github_signature(raw_body, request.headers.get("x-hub-signature-256", ""), GITHUB_WEBHOOK_SECRET)
    elif source == "stripe":
        from config.settings import STRIPE_WEBHOOK_SECRET
        _verify_stripe_signature(raw_body, request.headers.get("stripe-signature", ""), STRIPE_WEBHOOK_SECRET)
    else:
        raise HTTPException(404, f"Unknown webhook source: {source}")


def _verify_github_signature(raw_body: bytes, signature_header: str, secret: str):
    """GitHub's documented scheme: X-Hub-Signature-256 is 'sha256=' + the
    hex HMAC-SHA256 of the raw request body, keyed with the webhook secret
    configured in the repo's Settings -> Webhooks."""
    if not secret:
        raise HTTPException(403, "GitHub webhook not configured")
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(403, "Missing X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(403, "Invalid GitHub signature")


def _verify_stripe_signature(raw_body: bytes, signature_header: str, secret: str, tolerance_seconds: int = 300):
    """Stripe's documented scheme (https://stripe.com/docs/webhooks/signatures):
    Stripe-Signature is 't=<timestamp>,v1=<hex hmac>[,v1=<hex hmac>...]'. The
    signed payload is '<timestamp>.<raw body>', HMAC-SHA256 keyed with the
    endpoint's signing secret. Implemented directly against that spec rather
    than the `stripe` package, which isn't a dependency of this project and
    there's currently no evidence Stripe is actually connected (no
    STRIPE_* value set anywhere) — this is Stripe's own published algorithm,
    not a custom scheme. Timestamp tolerance rejects replayed old deliveries."""
    if not secret:
        raise HTTPException(403, "Stripe webhook not configured")
    if not signature_header:
        raise HTTPException(403, "Missing Stripe-Signature")

    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    timestamp = parts.get("t")
    v1_sigs = [p.split("=", 1)[1] for p in signature_header.split(",") if p.startswith("v1=")]
    if not timestamp or not v1_sigs:
        raise HTTPException(403, "Malformed Stripe-Signature")

    try:
        if abs(time.time() - int(timestamp)) > tolerance_seconds:
            raise HTTPException(403, "Stripe signature timestamp outside tolerance")
    except ValueError:
        raise HTTPException(403, "Malformed Stripe-Signature timestamp")

    signed_payload = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in v1_sigs):
        raise HTTPException(403, "Invalid Stripe signature")


def github_handler(payload: dict) -> dict:
    if "commits" in payload:
        repo = payload.get("repository", {}).get("name", "unknown repo")
        pusher = payload.get("pusher", {}).get("name", "someone")
        messages = [c.get("message", "") for c in payload.get("commits", [])]
        text = f"New push to {repo} by {pusher}: {'; '.join(messages[:3])}"
        _announce(text, "info")
        return {"handled": "push", "summary": text}

    if "pull_request" in payload:
        pr = payload["pull_request"]
        action = payload.get("action", "")
        text = f"PR {action}: {pr.get('title','')} — {pr.get('html_url','')}"
        _announce(text, "info")
        return {"handled": "pull_request", "summary": text}

    if "issue" in payload:
        issue = payload["issue"]
        text = f"Issue {payload.get('action','')}: {issue.get('title','')}"
        try:
            from services.workshop import workshop
            workshop.update_project_status(payload.get("repository", {}).get("name", "unknown"), text)
        except Exception:
            pass
        _announce(text, "info")
        return {"handled": "issue", "summary": text}

    if payload.get("action") == "completed" and payload.get("workflow_run", {}).get("conclusion") == "failure":
        text = f"Build failed: {payload['workflow_run'].get('name','')}"
        _announce(text, "high")
        return {"handled": "workflow_failure", "summary": text}

    return {"handled": "github_generic", "summary": "GitHub event received"}


def stripe_handler(payload: dict) -> dict:
    event_type = payload.get("type", "")
    data = payload.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        amount = data.get("amount", 0) / 100
        text = f"Payment succeeded: ${amount:.2f}"
        _announce(text, "info")
        return {"handled": "payment_succeeded", "summary": text}

    if event_type == "payment_intent.payment_failed":
        text = f"Payment FAILED: {data.get('last_payment_error', {}).get('message', 'unknown reason')}"
        _announce(text, "high")
        return {"handled": "payment_failed", "summary": text}

    if event_type == "customer.subscription.created":
        text = "New subscription created"
        _announce(text, "info")
        return {"handled": "new_subscription", "summary": text}

    return {"handled": "stripe_generic", "summary": f"Stripe event: {event_type}"}


def custom_handler(payload: dict) -> dict:
    """Generic: JARVIS interprets the payload and responds."""
    from core.brain_v2 import brain
    result = brain.process_dict(f"Webhook received: {str(payload)[:500]}")
    return {"response": result["response"]}


def _announce(text: str, severity: str = "info"):
    try:
        from core.event_bus import bus
        if severity in ("high", "critical"):
            bus.alert(text, severity)
        else:
            bus.system(text)
    except Exception:
        pass


class WebhookManager:
    WEBHOOK_REGISTRY: dict[str, callable] = {
        "github": github_handler,
        "stripe": stripe_handler,
    }

    _log: list[dict] = []

    @classmethod
    def register(cls, name: str, handler: callable):
        cls.WEBHOOK_REGISTRY[name] = handler

    @classmethod
    def process(cls, source: str, payload: dict) -> dict:
        handler = cls.WEBHOOK_REGISTRY.get(source, custom_handler)
        try:
            result = handler(payload)
        except Exception as e:
            result = {"error": str(e)}

        cls._log.append({"source": source, "ts": datetime.now().isoformat(),
                         "result_summary": str(result)[:200]})
        cls._log[:] = cls._log[-200:]
        return result

    @classmethod
    def history(cls) -> list[dict]:
        return list(reversed(cls._log))
