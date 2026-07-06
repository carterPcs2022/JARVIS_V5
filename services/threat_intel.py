"""services/threat_intel.py — IP reputation lookups (AbuseIPDB) and
LLM-generated threat pattern / red-team-style analysis."""
import json
import os
import re
from pathlib import Path

import httpx


class ThreatIntelligence:

    def check_ip_reputation(self, ip: str) -> dict:
        api_key = os.getenv("ABUSEIPDB_KEY", "")
        if not api_key:
            return {"ip": ip, "known_bad": False, "note": "No API key configured (ABUSEIPDB_KEY)"}
        try:
            r = httpx.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": api_key, "Accept": "application/json"},
                timeout=10,
            )
            data = r.json().get("data", {})
            score = data.get("abuseConfidenceScore", 0)
            return {
                "ip": ip, "known_bad": score > 50, "score": score,
                "country": data.get("countryCode", ""), "reports": data.get("totalReports", 0),
            }
        except Exception:
            return {"ip": ip, "known_bad": False, "error": "lookup failed"}

    def get_latest_attack_patterns(self) -> list[dict]:
        """One "standard"-tier call to summarize recent public research
        into structured attack patterns — used to inform manual review,
        not to auto-update any detection rule."""
        from core.llm.router import think
        from core.tools.web import search

        results = search("latest API security attack patterns", max_results=3)
        context = "\n".join(r.get("snippet", "") for r in results)
        patterns = think(
            f"Based on this recent security research:\n{context}\n\n"
            f"List the top 5 attack patterns targeting AI APIs right now. "
            f'Format as JSON array: [{{"name":str, "description":str, "indicator":str, "countermeasure":str}}]',
            force_model="standard",
        )
        try:
            clean = re.sub(r"```json|```", "", patterns).strip()
            return json.loads(clean)
        except Exception:
            return []

    def red_team_analysis(self) -> str:
        """How would a sophisticated attacker target this specific
        system? One "fable"-tier call — genuinely on-demand only."""
        from core.llm.router import think
        return think(
            f"You are a security researcher doing a red team exercise.\n"
            f"JARVIS is a personal AI assistant with:\n"
            f"- FastAPI server on Render\n- API token authentication\n"
            f"- WebSocket chat interface\n- ElevenLabs voice generation\n"
            f"- Groq LLM backend\n- File-based memory storage\n"
            f"- Multiple public endpoints\n\n"
            f"How would a sophisticated attacker attempt to compromise this system?\n"
            f"What are the 5 most likely attack vectors?\n"
            f"What should be hardened immediately?\n\n"
            f"This is a defensive exercise to improve security. Be specific and actionable.",
            force_model="fable",
        )


threat_intel = ThreatIntelligence()
