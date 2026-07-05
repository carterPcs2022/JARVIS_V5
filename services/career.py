"""services/career.py — resume tailoring, cover letters, interview prep,
salary research."""


class CareerAssistant:

    def optimize_resume(self, resume: str, job_description: str) -> dict:
        from core.llm.router import think
        result = think(
            f"Job Description:\n{job_description[:1000]}\n\nResume:\n{resume[:2000]}\n\n"
            f"Analyze:\n1. Keywords in JD missing from resume\n2. Experience to emphasize\n"
            f"3. Specific resume improvements\n4. Match score (0-100%)\n"
            f"5. Rewritten resume summary for this role",
            force_model="fable",
        )
        return {"optimization": result}

    def cover_letter(self, resume: str, job_description: str, company: str) -> str:
        from core.llm.router import think
        return think(
            f"Write a compelling, personalized cover letter for:\n"
            f"Company: {company}\nJob: {job_description[:500]}\nBased on resume: {resume[:1000]}\n\n"
            f"Make it genuine, specific, and memorable. Not generic. Not sycophantic.",
            force_model="sonnet",
        )

    def interview_prep(self, job_description: str, company: str) -> dict:
        from core.llm.router import think
        questions = think(
            f"Generate 10 likely interview questions for:\nCompany: {company}\nRole: {job_description[:500]}\n\n"
            f"Include: behavioral, technical, and culture fit. Add ideal answer frameworks.",
            force_model="opus",
        )
        return {"company": company, "questions": questions}

    def salary_research(self, role: str, location: str = "") -> dict:
        from core.tools.web import search
        from core.llm.router import think
        results = search(f"{role} salary {location}", max_results=5)
        context = "\n".join(r.get("snippet", "") for r in results)
        analysis = think(
            f"Summarize salary data for {role} in {location}:\n{context}\n\n"
            f"Give: median, range, factors affecting pay, negotiation tips.",
            force_model="standard",
        )
        return {"role": role, "location": location, "analysis": analysis}


career = CareerAssistant()
