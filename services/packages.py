"""services/packages.py — persistent multi-package watchlist with periodic
status checks and delivery alerts. Complements (doesn't duplicate)
services/travel.py's package_tracker(), which only resolves a tracking
URL for a single lookup — this adds the stateful watchlist + scheduled
polling + delivery detection on top of it."""
import json
import time
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

PACKAGES_FILE = BASE_DIR / "memory" / "packages.json"


class PackageTracker:

    def add(self, tracking_number: str, carrier: str, description: str = "") -> dict:
        packages = self._load()
        package = {
            "id": f"pkg_{int(time.time())}", "tracking_number": tracking_number,
            "carrier": carrier.upper(), "description": description, "status": "pending",
            "last_update": None, "delivered": False, "added": datetime.now().isoformat(),
        }
        packages.append(package)
        self._save(packages)
        return package

    def check_status(self, tracking_number: str, carrier: str) -> dict:
        """No carrier API credentials configured here — falls back to a
        web search + LLM summary, same tier discipline as everything else
        that does this (instant tier, cheap)."""
        from core.tools.web import search
        from core.llm.router import think

        results = search(f"{carrier} tracking {tracking_number}", max_results=2)
        context = "\n".join(r.get("snippet", "") for r in results)
        status = think(
            f"What is the status of package {tracking_number} with {carrier}?\n"
            f"Context: {context}\nGive brief status update.",
            force_model="instant",
        )
        return {"tracking": tracking_number, "carrier": carrier, "status": status}

    def check_all(self) -> list[dict]:
        packages = self._load()
        updates = []
        for pkg in packages:
            if pkg.get("delivered"):
                continue
            status = self.check_status(pkg["tracking_number"], pkg["carrier"])
            pkg["last_update"] = status["status"]
            if "delivered" in status["status"].lower():
                pkg["delivered"] = True
                from core.event_bus import bus
                bus.alert(f"Package delivered: {pkg['description'] or pkg['tracking_number']}",
                         severity="info", category="PACKAGE")
            updates.append(pkg)
        self._save(packages)
        return updates

    def list_packages(self) -> list[dict]:
        return self._load()

    def _load(self) -> list:
        if PACKAGES_FILE.exists():
            try:
                return json.loads(PACKAGES_FILE.read_text())
            except Exception:
                return []
        return []

    def _save(self, packages: list):
        PACKAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PACKAGES_FILE.write_text(json.dumps(packages, indent=2))


packages = PackageTracker()
