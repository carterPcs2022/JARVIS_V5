"""services/vision.py — Vision service (delegates to core/tools/vision.py)."""
from core.tools.vision import analyze

def analyze_image(path: str, prompt: str = "Describe this image.") -> str:
    return analyze(path, prompt)


def identify_person_from_image(image_path: str) -> dict:
    """Describe a person in an image and cross-reference against people
    memory. Not real facial recognition — a description + text-similarity
    match against what JARVIS already knows about people you've mentioned."""
    from core.memory import recall_facts

    description = analyze(image_path, "Describe this person's appearance in detail. "
                          "Physical features, clothing, estimated age.")
    facts = recall_facts(description, k=3)

    return {
        "description": description,
        "possible_matches": facts,
        "jarvis_says": (
            f"I can see {description[:100]}. "
            + (f"This may be {facts[0]['fact']}" if facts else "I don't have this person on file.")
        ),
    }
