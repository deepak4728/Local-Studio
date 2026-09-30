from types import SimpleNamespace

from django.test import SimpleTestCase

from .order_drafting import StructuredDraftError, validate_structured_draft


class StructuredOrderDraftTests(SimpleTestCase):
    def setUp(self):
        self.menu = [SimpleNamespace(id=7, name="Soup", price="8.50")]

    def test_normalizes_modifiers_to_a_customer_question(self):
        draft = validate_structured_draft(
            {"items": [{"menu_item_id": 7, "quantity": 2, "modifiers": ["no salt"], "price": "0.01"}]},
            self.menu,
        )
        self.assertEqual(draft["items"], [{"menu_item_id": 7, "quantity": 2}])
        self.assertTrue(draft["warnings"])
        self.assertTrue(draft["questions"])

    def test_rejects_provider_item_outside_catalog(self):
        with self.assertRaises(StructuredDraftError):
            validate_structured_draft({"items": [{"menu_item_id": 99, "quantity": 1}]}, self.menu)
