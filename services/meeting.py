"""services/meeting.py — meeting transcription + action-item extraction
via Groq Whisper."""
import os


class MeetingTranscriber:

    def transcribe_and_analyze(self, audio_path: str) -> dict:
        transcript = self._transcribe(audio_path)
        if not transcript:
            return {"error": "Transcription failed or produced no text"}

        from core.llm.router import think
        analysis = think(
            f"Analyze this meeting transcript:\n\n{transcript}\n\n"
            f"Extract:\n1. Key decisions made\n2. Action items (who does what by when)\n"
            f"3. Key discussion points\n4. Open questions / unresolved items\n"
            f"5. Follow-up meetings needed\n6. One-paragraph executive summary",
            force_model="research",
        )

        return {
            "transcript": transcript, "analysis": analysis,
            "summary": self._extract_summary(analysis), "actions": self._extract_actions(analysis),
        }

    def _transcribe(self, audio_path: str) -> str:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(audio_path, f.read()), model="whisper-large-v3-turbo", response_format="text",
            )
        return str(result)

    def _extract_summary(self, analysis: str) -> str:
        lines = analysis.split("\n")
        for i, line in enumerate(lines):
            if "summary" in line.lower():
                return "\n".join(lines[i + 1:i + 4])
        return analysis[:300]

    def _extract_actions(self, analysis: str) -> list[str]:
        lines = analysis.split("\n")
        actions = []
        in_actions = False
        for line in lines:
            if "action" in line.lower():
                in_actions = True
            elif in_actions and line.strip().startswith("-"):
                actions.append(line.strip("- "))
            elif in_actions and line.strip() == "":
                break
        return actions


meeting = MeetingTranscriber()
