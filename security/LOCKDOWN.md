# JARVIS V5 Security Lockdown

This repository treats the model as an untrusted decision-maker and the gateway as the security boundary.

## Required invariants

- Production API authentication fails closed when `JARVIS_API_TOKEN` is missing.
- Wildcard CORS never enables credentialed requests.
- Model-selected tools execute only through `core.tool_gateway.ToolGateway`.
- Tool arguments are schema-validated before handlers run.
- Confirmation-required tools never execute from an unconfirmed agent turn.
- Browser fetching rejects loopback/private/link-local destinations and validates redirects.
- GitHub review content is treated as untrusted data, not instructions.
- Secrets are never written to the tool audit trail.
- Tool calls are bounded by per-call input/output limits and a small in-process rate limit.
- Self-evolution remains human-approved and cannot auto-push or auto-deploy.

See `docs/AUDIT.md` for the historical audit and this directory for regression tests.
