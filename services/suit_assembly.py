"""services/suit_assembly.py — the boot sequence JARVIS streams to the HUD
on startup: every subsystem coming online one by one, Iron-Man-style."""


class SuitAssembly:

    SYSTEMS = [
        ("Arc Reactor",         "power_core", 0.5),
        ("Neural Interface",    "brain",      1.0),
        ("Repulsor Systems",    "groq",       1.5),
        ("Flight Systems",      "network",    2.0),
        ("Targeting Systems",   "sentinel",   2.5),
        ("Structural Scanners", "memory",     3.0),
        ("Comm Array",          "websocket",  3.5),
        ("Friday Backup",       "friday",     4.0),
        ("Retinal Scanner",     "retinal",    4.25),
        ("All Systems",         "complete",   4.5),
    ]

    def run_assembly_sequence(self, groq_ok: bool | None = None) -> list[dict]:
        """Returns a list of assembly events with timing. Each event streams
        to the HUD via the event bus; the HUD animates each system coming
        online at the given delay (seconds from sequence start).

        Pass the already-known groq_ok (e.g. from the startup LLM probe) to
        avoid a duplicate live check_groq() network call — calling it again
        here would just be one more request stacked onto boot."""
        from core.tools.system import snapshot
        if groq_ok is None:
            from core.llm.router import check_groq
            groq_ok = check_groq()

        sys_data = snapshot()
        events = []

        for name, system, delay in self.SYSTEMS:
            status = self._check_system(system, sys_data, groq_ok)
            events.append({
                "type": "suit_assembly",
                "system": name,
                "status": status,
                "delay": delay,
                "icon": self._icon(status),
            })

        all_ok = all(e["status"] == "online" for e in events[:-1])
        final_msg = (
            "All systems nominal. Ready for deployment, sir."
            if all_ok else
            "Some systems require attention. Proceeding with caution."
        )
        events.append({
            "type": "suit_complete",
            "message": final_msg,
            "delay": 5.0,
        })
        return events

    def _check_system(self, system: str, sys_data: dict, groq_ok: bool) -> str:
        checks = {
            "power_core": lambda: "online",
            "brain":      lambda: "online" if groq_ok else "degraded",
            "groq":       lambda: "online" if groq_ok else "offline",
            "network":    lambda: "online" if sys_data.get("cpu_percent", 100) < 90 else "degraded",
            "sentinel":   lambda: "online",
            "memory":     lambda: "online",
            "websocket":  lambda: "online",
            "friday":     lambda: "standby",
            "retinal":    self._retinal_status,
            "complete":   lambda: "online",
        }
        return checks.get(system, lambda: "online")()

    def _retinal_status(self) -> str:
        try:
            from services.retinal_scan import retinal
            return "online" if retinal.status().get("enrolled") else "standby"
        except Exception:
            return "standby"

    def _icon(self, status: str) -> str:
        return {"online": "✓", "degraded": "⚠", "offline": "✗", "standby": "◎"}.get(status, "–")


assembly = SuitAssembly()
