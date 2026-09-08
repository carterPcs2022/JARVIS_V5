"""Bounded self-evolution coordinator.

Turns the existing Level-1/2/3 self-improvement pieces into a repeatable,
observable improvement loop. It may analyze, generate candidates, test them,
and queue them for human approval. It never auto-approves, commits, pushes,
or deploys a rewrite, and it stops after a small configured number of cycles.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvolutionPolicy:
    max_cycles: int = 2
    max_candidates_per_cycle: int = 3
    require_human_approval: bool = True
    allow_auto_deploy: bool = False
    allow_auto_push: bool = False


class SelfEvolutionCoordinator:
    def __init__(self, policy: EvolutionPolicy | None = None):
        self.policy = policy or EvolutionPolicy()
        if self.policy.max_cycles < 1 or self.policy.max_cycles > 5:
            raise ValueError("max_cycles must be between 1 and 5")
        if not self.policy.require_human_approval or self.policy.allow_auto_deploy or self.policy.allow_auto_push:
            raise ValueError("self-evolution requires human approval and forbids automatic deploy/push")

    def run(self) -> dict:
        """Run bounded improvement cycles and return only observed results."""
        from core.self_improvement import self_improvement

        cycles = []
        for index in range(self.policy.max_cycles):
            result = self_improvement.run_improvement_cycle()
            cycles.append({"cycle": index + 1, "result": result})
            # A cycle with no candidates cannot productively recurse forever.
            if result.get("queued", 0) == 0:
                break
        return {
            "cycles": cycles,
            "approval_required": True,
            "auto_deploy": False,
            "auto_push": False,
        }


evolution = SelfEvolutionCoordinator()
