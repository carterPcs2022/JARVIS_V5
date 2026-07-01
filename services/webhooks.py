"""services/webhooks.py — Universal webhook receiver. GitHub, Stripe, IFTTT,
Zapier, or anything else that can POST JSON."""
from datetime import datetime


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
