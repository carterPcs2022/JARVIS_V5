"""core/interfaces/ — the shared protocols introduced in the V5 -> V6
migration: ReasoningStrategy, LLMProvider, Tool, Agent.

Deliberately not re-exported here. Each submodule builds its registry by
importing the real implementations lazily (inside a function, not at
module load time) — importing this package must stay cheap, and importing
any one interface must not drag in every reasoning/agent/provider module
whether or not the caller needs it.

Nothing in the existing codebase is required to use these yet. Every
module that now implements one of these interfaces (see the "ReasoningStrategy
adapter" / "LLMProvider adapter" / etc. sections added to each) keeps its
original functions/classes and existing callers (core/orchestrator.py,
server/routes/*.py, ...) working completely unchanged. This is Phase 1 of
the V6 migration (see docs/AUDIT.md): introduce the interfaces and adapt
existing modules to implement them, in place, without moving files or
changing any request path yet. Phase 2 wires a Cognitive Router up to use
them as the primary path.
"""
