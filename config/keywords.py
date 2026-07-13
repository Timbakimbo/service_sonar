from pathlib import Path


KEYWORDS = [
    # Zentrum Bayern Familie und Soziales
    "ZBFS",
    "Zentrum Bayern Familie",
    "Zentrum Bayern Familie & Soziales",
    
    # Leistungen
    "Elterngeld Bayern",
    "Familiengeld Bayern",
    "Kindergeld Bayern",
    "Landeserziehungsgeld Bayern",
    "Elterngeld Plus Bayern",

    
    # Grobe Suchanfragen (wie ein Mensch) BEISPIELE
    "Familienunterstützung Bayern",
    "Familienunterstützung Bayern Probleme",
    "Familienunterstützung Bayern Antrag Erfahrungen",
    "berhördliche Unterstützung Familie Bayern",
    "staatliche Unterstützung Familie Bayern",
    "Elterngeld Antrag Probleme Erfahrungen",
    "Elterngeld abgelehnt",
    "Kindergeld abgelehnt Erfahrungen",
    "Elterngeld Bearbeitungszeit zu lang",
    "Familiengeld Bayern Widerspruch",
    "Familienprämien Bayern",
    "Elterngeld Bescheid fehlerhaft",
    "Sozialamt Bayern nicht erreichbar",
    "Antrag Bayern abgelehnt Familie",
]

HUMAN_DECISIONS_PATH = Path("data/evaluation/human_decisions.json")
EVALUATOR_PATH = Path("data/evaluation/evaluator_output.json")


def get_effective_keywords(
    decisions_path: Path = HUMAN_DECISIONS_PATH,
    evaluator_path: Path = EVALUATOR_PATH,
) -> list[str]:
    """Apply only human-accepted keyword decisions to the curated seed list."""
    effective = list(KEYWORDS)
    from agents.human_feedback import accepted_human_decisions

    for decision in accepted_human_decisions(evaluator_path, decisions_path):
        keyword = str(decision.get("target", "")).strip()
        if not keyword:
            continue
        if decision.get("action_type") == "keyword_add" and keyword not in effective:
            effective.append(keyword)
        elif decision.get("action_type") == "keyword_remove":
            effective = [item for item in effective if item != keyword]
    return effective
