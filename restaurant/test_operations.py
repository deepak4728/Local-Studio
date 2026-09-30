from decimal import Decimal
from django.test import TestCase
from api.models import BusinessProfile
from .models import Ingredient, Purchase, PurchaseLine, StockMovement, Wastage
from .operations import receive_purchase, record_wastage

class OperationsTests(TestCase):
    def setUp(self):
        self.business = BusinessProfile.get_or_create_default()
        self.ingredient = Ingredient.objects.create(business=self.business, name="Tomato", unit="kg", reorder_level=2)

    def test_purchase_and_wastage_are_audited(self):
        purchase = Purchase.objects.create(business=self.business)
        PurchaseLine.objects.create(purchase=purchase, ingredient=self.ingredient, quantity=Decimal("5"), unit_cost=Decimal("3"))
        receive_purchase(purchase, "staff")
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.stock_on_hand, Decimal("5.000"))
        wastage = Wastage.objects.create(business=self.business, ingredient=self.ingredient, quantity=Decimal("1"), reason="spoiled")
        record_wastage(wastage, "staff")
        self.ingredient.refresh_from_db()
        self.assertEqual(self.ingredient.stock_on_hand, Decimal("4.000"))
        self.assertEqual(StockMovement.objects.count(), 2)
