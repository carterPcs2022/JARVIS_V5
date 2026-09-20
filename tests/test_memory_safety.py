"""Regression tests for memory safety boundaries."""


def test_save_turn_does_not_bypass_redaction(monkeypatch, tmp_path):
    import core.memory as memory

    monkeypatch.setattr(memory, "SHORT_TERM_FILE", tmp_path / "short.json")
    monkeypatch.setattr(memory, "CONVERSATIONS_FILE", tmp_path / "conversations.json")
    monkeypatch.setattr(memory, "_auto_extract_facts", lambda _text: None)

    class Shield:
        def scan_and_redact(self, value):
            return "[REDACTED]"

    import core.protocols as protocols
    monkeypatch.setattr(protocols, "shield", Shield())
    monkeypatch.setattr(memory, "_save", lambda *_args: True)
    monkeypatch.setattr(memory, "_append_conversation", lambda *_args: None)

    memory.save_turn("secret user text", "secret assistant text")
    turns = memory._load(memory.SHORT_TERM_FILE)
    assert turns[0]["user"] == "[REDACTED]"
    assert turns[0]["ai"] == "[REDACTED]"
