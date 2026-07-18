"""services/combat_mode.py — contextual combat mode, driven by
services/threat_detector.py's per-message classification.

Distinct from services/situation_room.py (manually activated, no polling-rate
change) — this is auto-engaged from message content and additionally tracks
telemetry poll rate + HUD theme. Reuses situation_room's state.voice_mode
convention so both agree on how JARVIS should speak while either is active.

engage()/disengage() are the only state mutators. Soft-confirm handling
(confidence between COMBAT_MODE_SOFT_CONFIRM_MIN and _THRESHOLD) is the
caller's responsibility (server/routes/chat.py) — this module only exposes
the threshold constants and the pending-confirm flag so that logic lives in
one place instead of being duplicated.
"""
import time
from enum import Enum

from config.settings import (
    COMBAT_MODE_CONFIDENCE_THRESHOLD,
    COMBAT_MODE_SOFT_CONFIRM_MIN,
    COMBAT_MODE_TIMEOUT_MINUTES,
)


class CombatState(Enum):
    IDLE = "idle"
    COMBAT = "combat"


class CombatMode:

    def __init__(self):
        self._state = CombatState.IDLE
        self._engaged_at: float | None = None
        self._pending_confirm = False

    def status(self) -> dict:
        self._check_timeout()
        return {
            "state": self._state.value,
            "pending_confirm": self._pending_confirm,
            "engaged_at": self._engaged_at,
        }

    def is_engaged(self) -> bool:
        self._check_timeout()
        return self._state == CombatState.COMBAT

    def _check_timeout(self):
        if self._state == CombatState.COMBAT and self._engaged_at is not None:
            elapsed_minutes = (time.time() - self._engaged_at) / 60
            if elapsed_minutes >= COMBAT_MODE_TIMEOUT_MINUTES:
                self.disengage(reason="auto_timeout")

    def engage(self, message: str, confidence: float, category: str) -> dict:
        """Switch to COMBAT: HUD theme, telemetry rate, HA scene, alert voice, audit log."""
        self._state = CombatState.COMBAT
        self._engaged_at = time.time()
        self._pending_confirm = False

        from core.state import state
        state.set("combat_mode", True)
        state.set("voice_mode", "combat")
        state.set("hud_theme", "combat")
        state.set("hud_poll_rate", "fast")

        try:
            from services.home_automation import activate_scene
            activate_scene("red_alert")
        except Exception as e:
            print(f"[CombatMode] red_alert scene failed to activate: {e}")

        try:
            from services.elevenlabs_voice import speak_with_mode
            speak_with_mode("Combat mode engaged. I'm here.", mode="combat")
        except Exception as e:
            print(f"[CombatMode] alert voice failed to play: {e}")

        from services.audit_log import audit_log
        audit_log.record(
            "COMBAT_MODE_ENGAGE",
            details={"message": message, "confidence": confidence, "category": category},
            result="alert",
        )

        # Phase 2: pre-stage the next likely action so a follow-up request
        # gets an instant answer instead of starting from zero. Backgrounded
        # (see services/combat_staging.py) — never adds latency to engage()
        # itself, which is on the hot path of every classified message.
        try:
            from services.combat_staging import stage_for_category
            stage_for_category(category)
        except Exception as e:
            print(f"[CombatMode] staging failed to start: {e}")

        return self.status()

    def disengage(self, reason: str = "manual") -> dict:
        """Revert to IDLE: HUD theme, telemetry rate, HA scene, voice mode."""
        was_engaged = self._state == CombatState.COMBAT
        self._state = CombatState.IDLE
        self._engaged_at = None
        self._pending_confirm = False

        from core.state import state
        state.set("combat_mode", False)
        state.set("voice_mode", "normal")
        state.set("hud_theme", "idle")
        state.set("hud_poll_rate", "normal")

        try:
            from services.combat_staging import clear as clear_staged
            clear_staged()
        except Exception as e:
            print(f"[CombatMode] clearing staged actions failed: {e}")

        if was_engaged:
            try:
                from services.home_automation import activate_scene
                activate_scene("morning")
            except Exception as e:
                print(f"[CombatMode] revert-to-morning scene failed: {e}")

            from services.audit_log import audit_log
            audit_log.record(
                "COMBAT_MODE_DISENGAGE",
                details={"reason": reason},
                result="success",
            )

        return self.status()

    def handle_classification(self, message: str, classification: dict) -> dict:
        """Apply threat_detector.classify()'s output to the state machine.
        Returns status plus a 'soft_confirm_prompt' string when JARVIS should
        ask a check-in question instead of auto-engaging."""
        category = classification.get("category", "none")
        confidence = classification.get("confidence", 0.0)
        is_threat = classification.get("is_threat", False)

        if category == "stand_down":
            result = self.disengage(reason="stand_down_message")
            return {**result, "soft_confirm_prompt": None}

        # confidence only means something once the classifier has actually
        # flagged this as a threat — a model that's confidently correct
        # that something ISN'T a threat still reports high confidence, just
        # in the opposite direction. Without this gate, a hypothetical
        # safety question like "is it dangerous to mix bleach and ammonia"
        # (is_threat=False, confidence=1.0) engaged combat mode purely
        # because the number was high, despite the classifier itself
        # correctly saying this wasn't a threat.
        if not is_threat:
            self._pending_confirm = False
            return {**self.status(), "soft_confirm_prompt": None}

        if confidence >= COMBAT_MODE_CONFIDENCE_THRESHOLD:
            result = self.engage(message, confidence, category)
            return {**result, "soft_confirm_prompt": None}

        if COMBAT_MODE_SOFT_CONFIRM_MIN <= confidence < COMBAT_MODE_CONFIDENCE_THRESHOLD:
            if self._pending_confirm:
                # Second consecutive soft-signal message — treat as confirmation.
                result = self.engage(message, confidence, category)
                return {**result, "soft_confirm_prompt": None}
            self._pending_confirm = True
            return {**self.status(), "soft_confirm_prompt": "Everything okay?"}

        self._pending_confirm = False
        return {**self.status(), "soft_confirm_prompt": None}


combat_mode = CombatMode()
