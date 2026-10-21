import re
import math
from datetime import datetime


def _classification_score(piece, field):
    """Score a field match using cheap, deterministic local signals."""
    lowered = piece.casefold().strip()
    label = str(field.get("label", ""))
    kind = field.get("type", "text")
    words = set(re.findall(r"[a-z0-9]+", lowered))
    label_tokens = {token for token in re.findall(r"[a-z0-9]+", label.casefold()) if len(token) > 2}
    score = 0.0

    # Labels and explicit "email ..." / "phone ..." prefixes are useful
    # deterministic hints, especially for a single-box quick-fill message.
    overlap = len(label_tokens & words)
    if overlap:
        score += min(2.0, overlap * 1.25)
    if label.strip() and lowered.startswith(label.casefold().strip() + " "):
        score += 2.0

    if kind == "email" and re.search(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])", piece):
        score += 5.0
    if kind == "tel" and re.search(r"(?:\+?\d[\d ()-]{7,}\d)", piece):
        score += 5.0
    if kind == "date":
        date_patterns = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y")
        candidate = piece.strip()
        if any(_is_date(candidate, pattern) for pattern in date_patterns):
            score += 5.0
    if kind == "rating":
        rating = re.search(r"(?<!\d)([1-5])\s*(?:/\s*5|stars?|★)?(?!\d)", lowered)
        if rating and ("star" in lowered or "★" in lowered or "/5" in lowered or len(lowered) <= 8):
            score += 4.5
    if kind == "number":
        numeric = re.fullmatch(r"\s*(?:₹|rs\.?\s*)?\d+(?:[.,]\d+)?\s*(?:inr|rupees?)?\s*", lowered)
        if numeric:
            score += 3.5
        if re.search(r"(?:₹|\brs\.?\s*)\s*\d+(?:\.\d{1,2})?", lowered):
            score += 1.5
    if kind in {"select", "radio"}:
        for option in field.get("options", []):
            option_text = str(option).strip().casefold()
            if option_text and re.search(rf"(?<!\w){re.escape(option_text)}(?!\w)", lowered):
                score += 4.5
                break
    if kind == "textarea":
        word_count = len(re.findall(r"\w+", piece))
        if word_count >= 8 or re.search(r"[.!?].+[.!?]", piece):
            score += 2.0
    if kind == "item_cards" and re.search(r"\d+\s*(?:x|pcs?|pieces?|bottles?)\b", lowered):
        score += 3.0
    if kind == "text" and len(piece.split()) <= 5:
        score += 0.35
    return score


def _is_date(value, pattern):
    try:
        datetime.strptime(value, pattern)
        return True
    except ValueError:
        return False


def _softmax(scores, temperature=2.0):
    """Return a numerically stable, temperature-scaled distribution."""
    if not scores:
        return []
    temperature = max(float(temperature), 0.01)
    peak = max(scores)
    weights = [math.exp((score - peak) / temperature) for score in scores]
    total = sum(weights)
    return [weight / total for weight in weights]


def classify_text(text, fields):
    """Fast local System 1 classification with editable probability suggestions."""
    raw = str(text or "").strip()
    if not raw:
        return {"success": True, "model": "local-rules-v1", "classifications": []}
    # Split obvious value boundaries; leave prose intact when there are no delimiters.
    pieces = [part.strip() for part in re.split(r"[\n;]+", raw) if part.strip()]
    if len(pieces) == 1 and "," in raw and not re.search(r"\w+,\s*\w+@", raw):
        pieces = [part.strip() for part in raw.split(",") if part.strip()]
    results = []
    for piece in pieces:
        scores = [(field, _classification_score(piece, field)) for field in fields]
        scores.sort(key=lambda pair: pair[1], reverse=True)
        if not scores:
            continue
        probabilities = _softmax([score for _, score in scores])
        top_field, _top_score = scores[0]
        distribution = [
            {"fieldId": field.get("id"), "fieldName": field.get("label"), "probability": round(probability, 4)}
            for (field, _score), probability in zip(scores, probabilities)
        ]
        results.append({
            "dataPoint": piece,
            "predictedFieldId": top_field.get("id"),
            "predictedFieldName": top_field.get("label"),
            "probability": distribution[0]["probability"],
            "distribution": distribution,
        })
    return {"success": True, "model": "local-rules-v1", "classifications": results}
