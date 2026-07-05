"""services/price_tracker.py — watch a product page, alert when the price
drops below a target. The source spec depended on a services.web_agent.
WebAgent class that doesn't exist in this codebase; uses
core.tools.web.fetch() (page text) + an LLM price extraction instead."""
import json
import time
from datetime import datetime
from pathlib import Path

from config.settings import BASE_DIR

WATCHES_FILE = BASE_DIR / "memory" / "price_watches.json"


class PriceTracker:

    def watch(self, product_name: str, url: str, target_price: float) -> dict:
        watches = self._load()
        watch = {
            "id": f"price_{int(time.time())}", "product": product_name, "url": url,
            "target_price": target_price, "current_price": None,
            "created": datetime.now().isoformat(), "last_checked": None, "triggered": False,
        }
        watches.append(watch)
        self._save(watches)
        return watch

    def check_all(self) -> list[dict]:
        """Check all un-triggered watches. Returns the ones that just triggered."""
        from core.tools.web import fetch
        from core.llm.router import think

        watches = self._load()
        triggered = []

        for watch in watches:
            if watch.get("triggered"):
                continue
            try:
                page_text = fetch(watch["url"], max_chars=3000)
                price_str = think(
                    f"Extract ONLY the current price of the main product from this page text. "
                    f"Reply with just the number, no currency symbol, no words. "
                    f"If you can't find a price, reply NONE.\n\n{page_text}",
                    force_model="instant",
                ).strip()
                if price_str.upper() == "NONE":
                    continue
                price = float("".join(c for c in price_str if c.isdigit() or c == "."))
                watch["current_price"] = price
                watch["last_checked"] = datetime.now().isoformat()

                if price <= watch["target_price"]:
                    watch["triggered"] = True
                    triggered.append(watch)
                    self._alert(watch, price)
            except Exception:
                pass

        self._save(watches)
        return triggered

    def _alert(self, watch: dict, price: float):
        from core.event_bus import bus
        message = f"Price alert! {watch['product']} dropped to ${price:.2f}. Your target was ${watch['target_price']:.2f}."
        bus.alert(message, severity="high", category="PRICE_ALERT")
        try:
            from services.voice import speak
            speak(message)
        except Exception:
            pass

    def list_watches(self) -> list[dict]:
        return self._load()

    def _load(self) -> list:
        if WATCHES_FILE.exists():
            try:
                return json.loads(WATCHES_FILE.read_text())
            except Exception:
                return []
        return []

    def _save(self, watches: list):
        WATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        WATCHES_FILE.write_text(json.dumps(watches, indent=2))


price_tracker = PriceTracker()
