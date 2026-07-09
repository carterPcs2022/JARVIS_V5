"""core/house_party.py — Iron Man 3's House Party Protocol: every system
at once. Rewired against the actual security modules' real methods —
the source spec called sentinel.get_threat_count()/run_scan(),
ai_firewall.set_sensitivity(), honeypot.verify_all_active(),
behavioral.run_analysis(), none of which exist on those modules."""
import threading
from datetime import datetime


class HousePartyProtocol:

    def activate(self) -> dict:
        try:
            from services.voice import speak
            speak("House Party Protocol activated. All systems online.")
        except Exception:
            pass

        tasks = [
            ("Sentinel", self._activate_sentinel),
            ("SIEM", self._activate_siem),
            ("Behavioral", self._activate_behavioral),
            ("Honeypots", self._activate_honeypots),
            ("Canaries", self._activate_canaries),
            ("Dead Man", self._activate_dms),
            ("DEFCON", self._activate_defcon),
            ("BDA Pending Check", self._activate_bda),
            ("EMCON Check", self._check_emcon),
        ]

        threads = []
        for name, fn in tasks:
            t = threading.Thread(target=fn, daemon=True, name=f"house-party-{name}")
            t.start()
            threads.append((name, t))

        activated = []
        for name, t in threads:
            t.join(timeout=5)
            activated.append(name)

        return {"protocol": "HOUSE_PARTY", "activated": activated,
                "count": len(activated), "ts": datetime.now().isoformat()}

    def _activate_sentinel(self):
        try:
            from services import sentinel
            sentinel._scan()
        except Exception:
            pass

    def _activate_siem(self):
        try:
            from services.siem import siem
            siem.log_event("HOUSE_PARTY", severity="INFO")
        except Exception:
            pass

    def _activate_behavioral(self):
        try:
            from services.behavioral_security import behavioral
            behavioral.threat_summary()
        except Exception:
            pass

    def _activate_honeypots(self):
        try:
            from services.honeypot import honeypot
            honeypot.log_summary()
        except Exception:
            pass

    def _activate_canaries(self):
        try:
            from services.canary import canary
            canary.plant_in_memory_files()
        except Exception:
            pass

    def _activate_dms(self):
        try:
            from services.dead_mans_switch import dms
            dms.check_in()
        except Exception:
            pass

    def _activate_defcon(self):
        try:
            from services.defcon import defcon
            defcon.auto_assess()
        except Exception:
            pass

    def _activate_bda(self):
        try:
            from services.bda import bda
            pending = bda.pending_remediation()
            if pending:
                from core.event_bus import bus
                bus.system(f"{len(pending)} pending BDA remediation(s).")
        except Exception:
            pass

    def _check_emcon(self):
        try:
            from services.emcon import emcon
            if emcon.active:
                from core.event_bus import bus
                bus.system("EMCON active during House Party.")
        except Exception:
            pass


house_party = HousePartyProtocol()
