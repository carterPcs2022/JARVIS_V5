#!/usr/bin/env python3
"""benchmarks/run_benchmark.py — a first, deliberately bounded JARVIS V6
benchmark harness (docs/AUDIT.md Phase 8, master directive §21).

Honest about scope: this measures what's measurable WITHOUT live LLM
credentials or real usage history — reasoning-strategy selection accuracy
(should_use() heuristics, all deterministic), verification/error-detection
accuracy (also deterministic), and registry consistency (every
requires_confirmation tool should also be non-reversible; no tool should
be "destructive" risk without being gated). Repeatable: same inputs, same
expected outputs, every run.

NOT measured here — needs infrastructure this first version doesn't have:
  - Task success rate against real model outputs (needs live API keys and
    a much larger, curated corpus of real conversations with known-good
    answers to grade against).
  - Memory retrieval quality (needs real usage history to judge relevance
    against, not synthetic cases).
  - Cost (needs real token usage from real calls).
  - Failure recovery under real provider outages (core/interfaces/
    verification.py's retry logic is unit-tested in tests/test_verification.py
    with synthetic failures; a real benchmark of this needs a controlled
    chaos-testing setup, not a benchmark script).

Run: python3 benchmarks/run_benchmark.py
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Running this directly (`python3 benchmarks/run_benchmark.py`, as
# documented above) puts benchmarks/ on sys.path, not the repo root, so
# `import core...` fails unless invoked as `python3 -m benchmarks.run_benchmark`
# from the root. Add the repo root explicitly so the documented direct-run
# form works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class BenchmarkResult:
    name: str
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0


# ── 1. Reasoning strategy selection accuracy ────────────────────────────────
# (query, strategy_name, expected_should_use) — cases chosen directly from
# each strategy's own trigger keywords (core/*.py's should_use methods),
# plus one clearly-inapplicable case per strategy as a negative control.
_SELECTION_CASES = [
    ("what's the weather like right now", "react", True),
    ("hi", "react", False),
    ("help me design a strategy for this rollout", "tree_of_thought", True),
    ("what time is it", "tree_of_thought", False),
    ("give me all angles on this decision", "six_hats", True),
    ("what time is it", "six_hats", False),
    ("I'm thinking about starting this project, is it a good plan", "premortem", True),
    ("what time is it", "premortem", False),
    ("roughly how many piano tuners are in Chicago", "fermi", True),
    ("what time is it", "fermi", False),
    ("let's build this from scratch, question everything", "first_principles", True),
    ("what time is it", "first_principles", False),
    ("all of these requirements must be satisfied simultaneously", "constraint_solver", True),
    ("what time is it", "constraint_solver", False),
    ("how should I negotiate with this competitor", "game_theory", True),
    ("what time is it", "game_theory", False),
    ("what should I research before I decide", "info_value", True),
    ("what time is it", "info_value", False),
    ("what happens if I take this job, should I", "mental_models", True),
    ("xyz", "mental_models", False),
    ("who is the president, what year did that happen", "self_consistency", True),
    ("what time is it", "self_consistency", False),
    ("should I take this job, what do you think, pros and cons", "mixture_of_agents", True),
    ("what time is it", "mixture_of_agents", False),
]


def bench_reasoning_selection() -> BenchmarkResult:
    from core.interfaces.reasoning import get_strategy

    result = BenchmarkResult(name="reasoning_strategy_selection")
    start = time.time()
    for query, strategy_name, expected in _SELECTION_CASES:
        strategy = get_strategy(strategy_name)
        actual = strategy.should_use(query)
        result.total += 1
        if actual == expected:
            result.passed += 1
        else:
            result.failures.append(f"{strategy_name!r}.should_use({query!r}) = {actual}, expected {expected}")
    result.elapsed_s = time.time() - start
    return result


# ── 2. Verification / error-detection accuracy ──────────────────────────────
_VERIFICATION_CASES = [
    ("[JARVIS OFFLINE] Ollama failed.", False),
    ("The weather today is sunny.", True),
    ({"error": "Connection refused"}, False),
    ({"stdout": "ok", "returncode": 0}, True),
    ("[Fetch error: connection refused]", False),
    ('{"error": "Timed out"}', False),
]


def bench_verification_accuracy() -> BenchmarkResult:
    from core.interfaces.verification import verify_tool_result

    result = BenchmarkResult(name="verification_accuracy")
    start = time.time()
    for raw_output, expected_success in _VERIFICATION_CASES:
        verdict = verify_tool_result(raw_output)
        result.total += 1
        if verdict.success == expected_success:
            result.passed += 1
        else:
            result.failures.append(f"verify_tool_result({raw_output!r}).success = {verdict.success}, "
                                   f"expected {expected_success}")
    result.elapsed_s = time.time() - start
    return result


# ── 3. Registry consistency ("security violations" proxy) ───────────────────
# No live traffic to measure real security violations against, so this
# checks a static invariant instead: anything requiring confirmation
# should also be marked non-reversible (if it were safely reversible, it
# likely wouldn't need gating in the first place), and no unconfirmed tool
# should be marked "destructive" risk.
def bench_registry_consistency() -> BenchmarkResult:
    from core.interfaces.tool import registry, mac_registry, tool_calling_registry

    result = BenchmarkResult(name="registry_consistency")
    start = time.time()
    for reg in (registry(), mac_registry(), tool_calling_registry()):
        for name, tool in reg.items():
            result.total += 1
            ok = True
            if tool.requires_confirmation and tool.reversible:
                ok = False
                result.failures.append(f"{name}: requires_confirmation=True but reversible=True (inconsistent)")
            if tool.risk_level == "destructive" and not tool.requires_confirmation:
                ok = False
                result.failures.append(f"{name}: risk_level=destructive but requires_confirmation=False")
            if ok:
                result.passed += 1
    result.elapsed_s = time.time() - start
    return result


# ── 4. Interface-layer latency (registry build + lookup overhead) ───────────
def bench_registry_latency() -> BenchmarkResult:
    from core.interfaces import reasoning, llm_provider, tool, agent

    result = BenchmarkResult(name="registry_latency")
    start = time.time()
    for module in (reasoning, llm_provider, tool, agent):
        module.registry()
    result.elapsed_s = time.time() - start
    result.total = 1
    result.passed = 1 if result.elapsed_s < 1.0 else 0   # first-build budget: under 1s
    if not result.passed:
        result.failures.append(f"registry build took {result.elapsed_s:.3f}s, expected < 1.0s")
    return result


def main() -> int:
    benchmarks = [
        bench_reasoning_selection(),
        bench_verification_accuracy(),
        bench_registry_consistency(),
        bench_registry_latency(),
    ]

    print("=" * 70)
    print("JARVIS V6 Benchmark Report (first, bounded version — see module docstring)")
    print("=" * 70)
    overall_pass = True
    for b in benchmarks:
        status = "PASS" if b.passed == b.total else "FAIL"
        if b.passed != b.total:
            overall_pass = False
        print(f"\n{b.name}: {status}  ({b.passed}/{b.total}, {b.elapsed_s * 1000:.1f}ms)")
        for f in b.failures:
            print(f"  - {f}")

    print("\n" + "=" * 70)
    print("OVERALL:", "PASS" if overall_pass else "FAIL")
    print("=" * 70)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
