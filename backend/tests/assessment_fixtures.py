"""Upgrade legacy provider fixtures with explicit concept evidence."""
import copy
import json


def grounded_json(value):
    value = copy.deepcopy(value)
    if "technical_accuracy" in value:
        value["accuracy_category"] = "partial"
        scores = value.get("criteria_scores", value.get("criterion_scores", {}))
        value["credited_concepts"] = []
        if not scores and "overall_score" in value:
            scores = {"Overall": value["overall_score"]}
        for name, score in scores.items():
            detail = value.get("criterion_details", {}).get(name, {})
            if isinstance(score, (int, float)) and score > 0:
                value["credited_concepts"].append({
                    "criterion": name, "points": score,
                    "concept": "Demonstrated list mutability" if name == "Overall" else name,
                    "evidence": detail.get("evidence", value.get("overall_evidence", "")),
                    "explanation": detail.get("explanation", "The excerpt explains that lists can change."),
                })
    return json.dumps(value)
