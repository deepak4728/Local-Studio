"""Provider-neutral, deterministic AI order drafting.

The model may suggest menu IDs and customer language only.  This module owns
all catalog, availability, modifier, quantity, and price decisions.
"""
import json
from decimal import Decimal
from typing import Any, Callable, Iterable, Protocol

from rest_framework.exceptions import ValidationError


class DraftProvider(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, str]]) -> dict[str, Any]: ...


class StructuredDraftError(ValueError):
    """The provider response was not a safe structured draft."""


def _parse_provider_response(response: dict[str, Any]) -> dict[str, Any]:
    try:
        content = response["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StructuredDraftError("Provider returned invalid order JSON.") from exc
    if not isinstance(parsed, dict):
        raise StructuredDraftError("Provider returned invalid order JSON.")
    return parsed


def validate_structured_draft(raw: dict[str, Any], menu_items: Iterable[Any]) -> dict[str, Any]:
    """Normalize an LLM proposal using the authoritative database catalog."""
    if not isinstance(raw.get("items"), list):
        raise StructuredDraftError("Draft items must be an array.")
    by_id = {item.id: item for item in menu_items}
    quantities: dict[int, int] = {}
    warnings = []
    questions = []
    for proposed in raw["items"]:
        if not isinstance(proposed, dict):
            raise StructuredDraftError("Draft items must be objects.")
        item_id = proposed.get("menu_item_id")
        quantity = proposed.get("quantity")
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise StructuredDraftError("Draft item IDs must be integers.")
        if item_id not in by_id:
            raise StructuredDraftError("Draft contains an item that is not on the available menu.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 50:
            raise StructuredDraftError("Draft quantities must be between 1 and 50.")
        quantities[item_id] = quantities.get(item_id, 0) + quantity
        if quantities[item_id] > 50:
            raise StructuredDraftError("Draft quantities must be between 1 and 50.")
        modifiers = proposed.get("modifiers", [])
        if not isinstance(modifiers, list) or any(
            not isinstance(modifier, (str, dict)) for modifier in modifiers
        ):
            raise StructuredDraftError("Draft modifiers must be strings or objects.")
        if modifiers:
            # Modifiers are deliberately not persisted or priced from model output.
            warnings.append(f"Modifiers for {by_id[item_id].name} need customer confirmation.")
            questions.append(f"Please confirm modifiers for {by_id[item_id].name}.")

    unmatched = raw.get("unmatched_items", [])
    if not isinstance(unmatched, list) or any(not isinstance(value, str) for value in unmatched):
        raise StructuredDraftError("unmatched_items must be an array of strings.")
    unmatched = [value[:200] for value in unmatched[:30]]
    if unmatched:
        questions.append("Please clarify the unmatched items before ordering.")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise StructuredDraftError("Draft notes must be text.")
    return {
        "items": [{"menu_item_id": item_id, "quantity": quantity} for item_id, quantity in quantities.items()],
        "notes": notes[:10000],
        "unmatched_items": unmatched,
        "warnings": list(dict.fromkeys(warnings)),
        "questions": list(dict.fromkeys(questions)),
    }


def build_authoritative_summary(*, customer_name: str, notes: str, draft: dict[str, Any], business: Any) -> dict[str, Any]:
    """Calculate every price from current DB rows; never trust provider prices."""
    item_payloads = draft["items"]
    menu_by_id = {item.id: item for item in business.menu_items.filter(is_available=True)}
    items = []
    subtotal = Decimal("0.00")
    for payload in item_payloads:
        item = menu_by_id.get(payload["menu_item_id"])
        if item is None:
            raise ValidationError({"items": ["One or more menu items became unavailable. Refresh the draft."]})
        line_total = (item.price * payload["quantity"]).quantize(Decimal("0.01"))
        subtotal += line_total
        items.append({"menu_item_id": item.id, "name": item.name, "quantity": payload["quantity"], "unit_price": str(item.price), "line_total": str(line_total)})
    subtotal = subtotal.quantize(Decimal("0.01"))
    discount = subtotal * (business.discount_percent / Decimal("100")) if business.discount_percent else Decimal("0.00")
    tax = subtotal * (business.tax_rate / Decimal("100")) if business.tax_rate else Decimal("0.00")
    return {"customer_name": customer_name, "notes": notes, "items": items, "subtotal": str(subtotal), "discount": str(discount.quantize(Decimal("0.01"))), "tax": str(tax.quantize(Decimal("0.01"))), "total": str((subtotal - discount + tax).quantize(Decimal("0.01")))}
