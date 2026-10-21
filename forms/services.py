import re
import math
from datetime import date
from django.core.exceptions import ValidationError


FIELD_TYPES = {"text", "textarea", "number", "email", "tel", "select", "radio", "date", "checkbox", "rating", "file", "item_cards"}


def validate_form_schema(schema):
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list) or not schema["fields"]:
        raise ValidationError("A form schema must contain at least one field.")
    if len(schema["fields"]) > 100:
        raise ValidationError("Use up to 100 fields per form.")
    seen = set()
    for field in schema["fields"]:
        if not isinstance(field, dict):
            raise ValidationError("Each field must be an object.")
        field_id = str(field.get("id", "")).strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", field_id):
            raise ValidationError("Field ids must start with a letter and contain only letters, digits, _ or -.")
        if field_id in seen:
            raise ValidationError(f"Duplicate field id: {field_id}.")
        seen.add(field_id)
        if not str(field.get("label", "")).strip():
            raise ValidationError(f"Field {field_id} requires a label.")
        if field.get("type") not in FIELD_TYPES:
            raise ValidationError(f"Field {field_id} has an unsupported type.")
        if field.get("type") in {"select", "radio"}:
            options = field.get("options")
            if not isinstance(options, list) or not options or any(not isinstance(option, str) or not option.strip() for option in options):
                raise ValidationError(f"Field {field_id} requires a non-empty list of text options.")
        if field.get("type") in {"number", "rating"}:
            try:
                bounds = [float(field[key]) for key in ("min", "max") if field.get(key) is not None]
                if not all(math.isfinite(bound) for bound in bounds) or (len(bounds) == 2 and bounds[0] > bounds[1]):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError(f"Field {field_id} requires valid minimum and maximum values.")
        condition = field.get("visibleWhen")
        if condition:
            if not isinstance(condition, dict) or condition.get("field") not in seen:
                # Conditions may refer to a field declared later, validated below.
                if not isinstance(condition, dict):
                    raise ValidationError(f"Field {field_id} has an invalid visibility condition.")
    for field in schema["fields"]:
        condition = field.get("visibleWhen")
        if condition and condition.get("field") not in seen:
            raise ValidationError(f"Field {field['id']} refers to an unknown visibility field.")
    return schema


def _visible(field, data):
    condition = field.get("visibleWhen")
    if not condition:
        return True
    return data.get(condition.get("field")) == condition.get("equals")


def validate_submission(form, data):
    if not isinstance(data, dict):
        raise ValidationError("Submission data must be an object.")
    errors = {}
    for field in form.schema.get("fields", []):
        field_id = field["id"]
        if not _visible(field, data):
            continue
        value = data.get(field_id)
        if field.get("required") and (value is None or value == "" or value == []):
            errors[field_id] = "This field is required."
            continue
        if value in (None, "", []) or field_id in errors:
            continue
        kind = field.get("type")
        if kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value)):
            errors[field_id] = "Enter a valid email address."
        elif kind in {"number", "rating"}:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors[field_id] = "Enter a number."
                continue
            if isinstance(value, bool) or not math.isfinite(numeric):
                errors[field_id] = "Enter a finite number."
                continue
            if field.get("min") is not None and numeric < float(field["min"]):
                errors[field_id] = f"Enter a value of at least {field['min']}."
            if field.get("max") is not None and numeric > float(field["max"]):
                errors[field_id] = f"Enter a value no greater than {field['max']}."
        elif kind in {"select", "radio"} and value not in field.get("options", []):
            errors[field_id] = "Choose one of the listed options."
        elif kind == "checkbox" and not isinstance(value, bool):
            errors[field_id] = "Choose yes or no."
        elif kind == "date":
            try:
                date.fromisoformat(str(value))
            except ValueError:
                errors[field_id] = "Enter a date in YYYY-MM-DD format."
        elif kind in {"text", "textarea", "tel"} and (not isinstance(value, str) or len(value) > 10000):
            errors[field_id] = "Enter text of up to 10,000 characters."
        elif kind == "item_cards":
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                errors[field_id] = "Choose valid menu items."
        elif kind == "file" and value != "Uploaded document":
            errors[field_id] = "Upload a document."
    if errors:
        raise ValidationError(errors)
    return {
        field["id"]: data[field["id"]]
        for field in form.schema.get("fields", [])
        if field["id"] in data and _visible(field, data)
    }


def normalize_schema(schema, organization):
    """Bind reusable item-card fields to an organization-owned catalog."""
    import copy
    from .models import Catalog
    schema = copy.deepcopy(validate_form_schema(schema))
    for field in schema.get("fields", []):
        if field.get("type") != "item_cards":
            continue
        catalog_id = field.get("catalog_id")
        if catalog_id is None:
            field["catalog_id"] = Catalog.for_organization(organization).pk
        else:
            try:
                if isinstance(catalog_id, bool):
                    raise ValueError
                catalog_pk = int(catalog_id)
                if catalog_pk < 1:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise ValidationError({field["id"]: "Choose a catalog belonging to this organization."})
            if not Catalog.objects.filter(pk=catalog_pk, organization=organization).exists():
                raise ValidationError({field["id"]: "Choose a catalog belonging to this organization."})
            field["catalog_id"] = catalog_pk
    return schema


def save_item_selections(form, submission, data, payload):
    """Persist authoritative item snapshots inside the submission transaction."""
    from .models import CatalogItem, ItemSelection, SelectionLine
    schema = normalize_schema(form.schema, form.organization)
    fields = [field for field in schema['fields'] if field['type'] == 'item_cards']
    # Check every existing record, even if conditional visibility hides its field.
    existing = list(submission.item_selections.select_for_update())
    if any(item.status != ItemSelection.STATUS_PENDING or item.payment_status != ItemSelection.PAYMENT_PENDING for item in existing):
        raise ValidationError('This response has started processing and can no longer be edited.')
    result = []
    for field in fields:
        values = data.get(field['id'], [])
        if not isinstance(values, list):
            raise ValidationError({field['id']: 'Choose valid items and quantities.'})
        selected = []
        for value in values:
            try:
                raw_id = value.get('catalog_item_id', value.get('menu_item_id'))
                raw_quantity = value.get('quantity', 1)
                if isinstance(raw_id, bool) or isinstance(raw_quantity, bool):
                    raise ValueError
                item_id, quantity = int(raw_id), int(raw_quantity)
                if str(quantity) != str(raw_quantity) or not 1 <= quantity <= 50:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise ValidationError({field['id']: 'Choose valid items and whole quantities from 1 to 50.'})
            item = CatalogItem.objects.filter(pk=item_id, catalog_id=field['catalog_id'], catalog__organization=form.organization, is_available=True).first()
            if item is None:
                raise ValidationError({field['id']: 'An item is unavailable or belongs to another catalog.'})
            selected.append((item, quantity))
        selection = next((item for item in existing if item.field_id == field['id']), None)
        # The importer binds historical order IDs. Never accept an order ID from a respondent.
        if not selected and selection is None:
            continue
        if selection is None:
            selection = ItemSelection(submission=submission, field_id=field['id'], catalog_id=field['catalog_id'])
        selection.customer_name = str(payload.get('respondent_name') or data.get('customer_name', ''))[:200]
        selection.notes = str(data.get('notes', ''))[:10000]
        selection.save()
        selection.items.all().delete()
        for item, quantity in selected:
            SelectionLine.objects.create(selection=selection, catalog_item=item, name=item.name, quantity=quantity, unit_price=item.price)
        selection.recalculate_totals()
        result.append(selection)
    return result
