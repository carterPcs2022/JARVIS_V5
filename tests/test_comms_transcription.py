"""tests/test_comms_transcription.py — regression test for
services/comms.py::call_transcription()'s JSON-parse fallback, same
failure class as core/reflection.py's FINAL: leak: if the model doesn't
return clean JSON, the code used to fall back to dumping its entire raw
completion (an unbounded reasoning ramble) straight into the user-facing
"summary" field."""
from unittest import mock
from services.comms import comms


def test_summary_uses_parsed_json_when_valid():
    raw = '{"action_items": ["call back"], "decisions": [], "people": [], "summary": "Brief call."}'
    with mock.patch("services.comms.think", return_value=raw), \
         mock.patch("services.voice.transcribe", return_value="hello"):
        result = comms.call_transcription("fake.wav")
    assert result["summary"] == "Brief call."
    assert result["action_items"] == ["call back"]


def test_summary_falls_back_capped_when_model_rambles_instead_of_json():
    ramble = "Let me think about this transcript step by step. " * 50
    with mock.patch("services.comms.think", return_value=ramble), \
         mock.patch("services.voice.transcribe", return_value="hello"):
        result = comms.call_transcription("fake.wav")
    assert len(result["summary"]) <= 600
    assert result["summary"] == ramble.strip()[:600]
