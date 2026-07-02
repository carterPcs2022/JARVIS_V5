"""
core/domain_expert.py — JARVIS maintains specialized knowledge domains.
Each domain gets its own context, auto-injected when a query matches.
Pure keyword matching for detection — no LLM cost.
"""
import json
from datetime import datetime
from pathlib import Path
from config.settings import BASE_DIR

_DOMAINS_FILE = BASE_DIR / "memory" / "domains.json"


class DomainExpert:

    def __init__(self):
        self.DOMAINS: dict = self._load()

    def register_domain(self, name: str, description: str, key_files: list[str] | None = None,
                        key_concepts: list[str] | None = None, specialized_tools: list[str] | None = None) -> dict:
        domain = {
            "name": name, "description": description, "key_files": key_files or [],
            "key_concepts": key_concepts or [], "tools": specialized_tools or [],
            "context": self._build_domain_context(name, description, key_files or [], key_concepts or []),
            "registered": datetime.now().isoformat(),
        }
        self.DOMAINS[name.lower()] = domain
        self._save()
        return domain

    def _build_domain_context(self, name: str, description: str, key_files: list, concepts: list) -> str:
        parts = [f"Domain: {name}", f"Description: {description}"]
        if concepts:
            parts.append("Key concepts: " + ", ".join(concepts))
        if key_files:
            from core.tools.files import read_file
            for f in key_files[:3]:
                try:
                    content = read_file(f)
                    if content and "Error" not in content:
                        parts.append(f"File {f}:\n{content[:500]}")
                except Exception:
                    pass
        return "\n".join(parts)

    def detect_domain(self, query: str) -> str | None:
        q = query.lower()
        for domain_name, domain in self.DOMAINS.items():
            if domain_name in q:
                return domain_name
            for concept in domain.get("key_concepts", []):
                if concept.lower() in q:
                    return domain_name
        return None

    def get_domain_context(self, domain_name: str) -> str:
        domain = self.DOMAINS.get(domain_name.lower())
        return domain.get("context", "") if domain else ""

    def get_domain_system_prompt(self, domain_name: str, base_system: str) -> str:
        domain = self.DOMAINS.get(domain_name.lower())
        if not domain:
            return base_system
        return (base_system + f"\n\nDomain expertise active: {domain['name']}\n"
                f"{domain['description']}\nYou have deep knowledge of this domain.")

    def list_domains(self) -> list[dict]:
        return list(self.DOMAINS.values())

    def auto_register_from_workshop(self):
        """Every workshop project becomes a domain JARVIS is expert in."""
        try:
            from services.workshop import workshop
            for project in workshop.list_projects():
                self.register_domain(
                    name=project.get("name", ""), description=project.get("description", ""),
                    key_concepts=[project.get("name", "")],
                )
        except Exception as e:
            print(f"[DomainExpert] Auto-register from workshop failed: {e}")

    def _load(self) -> dict:
        if _DOMAINS_FILE.exists():
            try:
                return json.loads(_DOMAINS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        _DOMAINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DOMAINS_FILE.write_text(json.dumps(self.DOMAINS, indent=2))


domain_expert = DomainExpert()
