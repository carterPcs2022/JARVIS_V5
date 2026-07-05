"""core/working_memory.py — active attention management: 7 items max
(Miller's Law), evicts least-important. Free (no LLM calls) — safe to
call from the default pipeline, but left as an available module rather
than auto-wired since nothing in the existing pipeline currently
maintains per-turn salience tracking."""
from collections import OrderedDict


class WorkingMemory:

    def __init__(self, capacity: int = 7):
        self.capacity = capacity
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._salience: dict[str, float] = {}

    def hold(self, key: str, value: str, importance: float = 0.5):
        if len(self._memory) >= self.capacity and key not in self._memory:
            self._evict()
        self._memory[key] = value
        self._salience[key] = importance

    def retrieve(self, key: str) -> str | None:
        val = self._memory.get(key)
        if val is not None:
            self._salience[key] = min(1.0, self._salience.get(key, 0.5) + 0.1)
        return val

    def get_relevant(self, query: str) -> str:
        q_words = [w for w in query.lower().split() if len(w) > 3]
        relevant = {
            k: v for k, v in self._memory.items()
            if any(w in v.lower() for w in q_words)
        }
        return "\n".join(f"[{k}]: {v[:100]}" for k, v in relevant.items())

    def _evict(self):
        if self._salience:
            least = min(self._salience, key=self._salience.get)
            self._memory.pop(least, None)
            self._salience.pop(least, None)

    def summary(self) -> dict:
        return {"items": len(self._memory), "capacity": self.capacity, "keys": list(self._memory.keys())}

    def clear(self):
        self._memory.clear()
        self._salience.clear()


working_mem = WorkingMemory()
