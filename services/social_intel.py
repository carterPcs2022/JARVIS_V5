"""services/social_intel.py — pre-meeting intelligence briefs on people and
companies, combining JARVIS's own memory with a public web search."""


class SocialIntelligence:

    def person_brief(self, name: str, company: str = "", context: str = "") -> dict:
        from core.tools.web import search
        from core.llm.router import think
        from core.memory import recall_facts

        memory = recall_facts(name, k=5)
        memory_context = "\n".join(f["fact"] for f in memory) if memory else ""

        query = f"{name} {company}".strip()
        results = search(query, max_results=5)
        web_context = "\n".join(f"• {r.get('snippet','')}" for r in results if r.get("snippet"))

        li_results = search(f"{name} {company} LinkedIn", max_results=3)
        li_context = "\n".join(f"• {r.get('snippet','')}" for r in li_results if r.get("snippet"))

        brief = think(
            f"Generate a pre-meeting intelligence brief on:\n"
            f"Name: {name}\nCompany: {company}\nMeeting context: {context}\n\n"
            f"What JARVIS knows: {memory_context}\n"
            f"Public information: {web_context[:500]}\n"
            f"Professional background: {li_context[:500]}\n\n"
            f"Include:\n1. Who they are (2 sentences)\n2. What they're working on recently\n"
            f"3. What they care about\n4. Talking points / common ground\n"
            f"5. What to avoid\n6. How to make a good impression\n\n"
            f"JARVIS-style delivery. Briefing format.",
            force_model="research",
        )

        return {"name": name, "company": company, "brief": brief, "sources": len(results)}

    def company_brief(self, company: str) -> dict:
        """Brief on a company before a meeting or pitch. Two separate
        searches (overview + recent news) rather than a nonexistent
        dedicated news-search tool."""
        from core.tools.web import search
        from core.llm.router import think

        web_results = search(f"{company} company overview", max_results=5)
        news_results = search(f"{company} news 2026", max_results=5)

        web_context = "\n".join(f"• {r.get('snippet','')}" for r in web_results if r.get("snippet"))
        news_context = "\n".join(f"• {r.get('snippet','')}" for r in news_results if r.get("snippet"))

        brief = think(
            f"Intelligence brief on: {company}\n\n"
            f"Company info: {web_context[:500]}\nRecent news: {news_context[:500]}\n\n"
            f"Cover: what they do, size, recent news, opportunities, risks, "
            f"how to position yourself.",
            force_model="research",
        )
        return {"company": company, "brief": brief}


social = SocialIntelligence()
