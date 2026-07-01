"""services/content.py — Content creation suite: posts, emails, scripts, summaries."""


class ContentCreation:

    def write_post(self, topic: str, platform: str = "twitter", tone: str = "professional") -> str:
        from core.llm.router import think
        platform_specs = {
            "twitter":   "under 280 characters, punchy, 1-3 relevant hashtags",
            "x":         "under 280 characters, punchy, 1-3 relevant hashtags",
            "linkedin":  "professional tone, 3-5 short paragraphs, no more than 2 hashtags",
            "instagram": "engaging caption, line breaks for readability, 5-10 hashtags at the end",
            "threads":   "casual, conversational, under 500 characters",
        }
        spec = platform_specs.get(platform.lower(), platform_specs["twitter"])
        return think(f"Write a {tone} {platform} post about: {topic}\n\nFormat: {spec}", max_tokens=300)

    def write_email(self, to: str, subject: str, intent: str, context: str = "") -> str:
        from core.llm.router import think
        prompt = (
            f"Draft a professional email.\nTo: {to}\nSubject: {subject}\n"
            f"Intent: {intent}\n" + (f"Context: {context}\n" if context else "")
            + "Write it in a natural, non-robotic voice. Include a greeting and sign-off."
        )
        return think(prompt, max_tokens=400)

    def write_script(self, topic: str, format: str = "youtube", duration_minutes: int = 5) -> str:
        from core.llm.router import think
        words_target = duration_minutes * 150  # ~150 wpm speaking pace
        prompt = (
            f"Write a {format} script about '{topic}', targeting roughly {duration_minutes} "
            f"minutes ({words_target} words). Include: a hook, clear sections, natural "
            f"transitions, and a call to action at the end."
        )
        return think(prompt, max_tokens=min(2000, words_target * 2))

    def summarize(self, content: str, style: str = "bullets", max_words: int = 150) -> str:
        from core.llm.router import think
        style_map = {
            "bullets":    "as a bulleted list of key points",
            "paragraph":  "as a single flowing paragraph",
            "tldr":       "as a single TL;DR sentence",
            "executive":  "as an executive summary with a bolded key takeaway first",
        }
        instruction = style_map.get(style, style_map["bullets"])
        return think(f"Summarize the following {instruction}, max {max_words} words:\n\n{content}",
                     max_tokens=max_words * 2)

    def rewrite(self, content: str, goal: str) -> str:
        from core.llm.router import think
        return think(f"Rewrite the following to: {goal}\n\nOriginal:\n{content}",
                     max_tokens=len(content.split()) * 3 + 100)

    def proofread(self, content: str) -> dict:
        from core.llm.router import think
        raw = think(
            "Proofread this text. List issues (grammar, clarity, tone, structure) as bullets "
            "under 'ISSUES:', then give the corrected version under 'CORRECTED:'.\n\n" + content,
            max_tokens=len(content.split()) * 3 + 300,
        )
        issues, corrected = [], content
        if "CORRECTED:" in raw:
            issues_part, corrected = raw.split("CORRECTED:", 1)
            issues = [l.strip("-• ").strip() for l in issues_part.split("\n") if l.strip().startswith(("-", "•"))]
            corrected = corrected.strip()
        return {"issues": issues, "corrected": corrected}

    def generate_title(self, content: str, n_options: int = 5) -> list[str]:
        from core.llm.router import think
        raw = think(f"Generate {n_options} compelling title options for this content, one per line, "
                   f"no numbering:\n\n{content[:1000]}", max_tokens=150)
        return [line.strip("- ").strip() for line in raw.split("\n") if line.strip()][:n_options]

    def content_calendar(self, topics: list[str], days: int = 30) -> list[dict]:
        from core.llm.router import think
        prompt = (
            f"Plan {days} days of content across social platforms covering these topics: "
            f"{', '.join(topics)}. For each entry give: day number, platform, topic, and a "
            f"one-line content idea. Format as a numbered list."
        )
        raw = think(prompt, max_tokens=1200)
        entries = []
        for line in raw.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit()):
                entries.append({"raw": line})
        return entries


content_creation = ContentCreation()
