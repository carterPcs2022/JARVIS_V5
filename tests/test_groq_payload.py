from unittest import mock
import json

import core.llm.openai as groq


def test_compact_messages_keeps_system_and_latest_user():
    huge = "x " * 300000
    messages = [
        {"role": "system", "content": "JARVIS system"},
        {"role": "user", "content": "old turn"},
        {"role": "assistant", "content": huge},
        {"role": "user", "content": "Play my Breakup playlist"},
    ]
    with mock.patch.object(groq, "GROQ_MAX_REQUEST_BYTES", 12000), \
         mock.patch.object(groq, "GROQ_MAX_MESSAGE_CHARS", 4000):
        compacted, size = groq._compact_messages(messages)

    assert size <= 12000
    assert compacted[0]["role"] == "system"
    assert compacted[-1]["content"] == "Play my Breakup playlist"
    assert len(json.dumps(compacted)) < len(json.dumps(messages))


def test_compact_messages_does_not_change_small_request():
    messages = [
        {"role": "system", "content": "You are JARVIS."},
        {"role": "user", "content": "hello"},
    ]
    compacted, size = groq._compact_messages(messages)
    assert compacted == messages
    assert size > 0
