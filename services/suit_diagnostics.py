"""services/suit_diagnostics.py — Tony Stark-style suit status report,
generated from real system metrics. Pure computation, no LLM call."""


def suit_status_report() -> str:
    """"Repulsors online. Arc reactor at 94%. All systems go, sir."" """
    from core.tools.system import snapshot
    from core.state import state

    sys = snapshot()
    groq_ok = state.get("groq_available", False)

    cpu = sys.get("cpu_percent", 0)
    ram = sys.get("ram_used_pct", 0)
    disk = sys.get("disk_used_pct", 0)

    def status_word(pct: float) -> str:
        if pct > 90:
            return "critical"
        if pct > 70:
            return "elevated"
        return "nominal"

    lines = [
        f"Arc reactor: {100 - cpu:.0f}% power available.",
        f"Repulsors: {status_word(ram)}.",
        f"Structural integrity: {status_word(disk)}.",
        f"Weapons: {'online' if groq_ok else 'offline — Friday Protocol active'}.",
        f"Flight systems: nominal.",
        f"Shields: {'armed' if state.get('sentinel') else 'standby'}.",
    ]

    warnings = [l for l in lines if "critical" in l or "offline" in l]
    if warnings:
        lines.append(f"Warning: {len(warnings)} system(s) require attention.")
    else:
        lines.append("All systems nominal. Ready for deployment, sir.")

    return " ".join(lines)


def suit_status_full() -> dict:
    """Structured version for the HUD, alongside the spoken-style string."""
    from core.tools.system import snapshot
    from core.state import state

    sys = snapshot()
    return {
        "narrative": suit_status_report(),
        "arc_reactor_pct": round(100 - sys.get("cpu_percent", 0), 1),
        "repulsors_pct": round(100 - sys.get("ram_used_pct", 0), 1),
        "structural_pct": round(100 - sys.get("disk_used_pct", 0), 1),
        "weapons_online": bool(state.get("groq_available", False)),
        "shields_armed": bool(state.get("sentinel", False)),
        "friday_backup": bool(state.get("friday_online", False)),
    }
