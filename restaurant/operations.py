"""Deterministic stock and operational accounting services."""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Ingredient, LowStockAlert, Recipe, StockMovement, Wastage, PurchaseLine, SecurityAuditLog

@transaction.atomic
def deduct_order_inventory(order, actor=""):
    """Deduct each recipe ingredient exactly once for a completed order."""
    key = f"order:{order.pk}:sale"
    if StockMovement.objects.filter(order=order, reason=StockMovement.SALE).exists():
        return 0
    total = 0
    for item in order.items.select_related("menu_item").all():
        try: recipe = item.menu_item.recipe
        except Recipe.DoesNotExist: continue
        multiplier = Decimal(item.quantity) / (recipe.yield_quantity or Decimal("1"))
        for line in recipe.ingredients.select_related("ingredient"):
            ingredient = Ingredient.objects.select_for_update().get(pk=line.ingredient_id)
            quantity = -(line.quantity * multiplier)
            StockMovement.objects.create(business=order.business, ingredient=ingredient, order=order,
                quantity=quantity, reason=StockMovement.SALE, idempotency_key=f"{key}:{ingredient.pk}")
            ingredient.stock_on_hand += quantity
            ingredient.save(update_fields=["stock_on_hand"])
            if ingredient.is_low_stock:
                LowStockAlert.objects.get_or_create(business=order.business, ingredient=ingredient, acknowledged_at=None)
            total += 1
    SecurityAuditLog.record(order.business, "inventory.order_deducted", actor=actor,
        object_type="order", object_id=order.pk, metadata={"movements": total})
    return total

@transaction.atomic
def receive_purchase(purchase, actor=""):
    for line in purchase.lines.select_related("ingredient"):
        ingredient = Ingredient.objects.select_for_update().get(pk=line.ingredient_id)
        ingredient.stock_on_hand += line.quantity
        ingredient.unit_cost = line.unit_cost
        ingredient.save(update_fields=["stock_on_hand", "unit_cost"])
        StockMovement.objects.create(business=purchase.business, outlet=purchase.outlet, ingredient=ingredient,
            quantity=line.quantity, reason=StockMovement.PURCHASE, idempotency_key=f"purchase:{purchase.pk}:{line.pk}")
    SecurityAuditLog.record(purchase.business, "inventory.purchase_received", actor=actor,
        object_type="purchase", object_id=purchase.pk, metadata={"lines": purchase.lines.count()})

def record_wastage(wastage, actor=""):
    with transaction.atomic():
        ingredient = Ingredient.objects.select_for_update().get(pk=wastage.ingredient_id)
        ingredient.stock_on_hand -= wastage.quantity; ingredient.save(update_fields=["stock_on_hand"])
        StockMovement.objects.create(business=wastage.business, outlet=wastage.outlet, ingredient=ingredient,
            quantity=-wastage.quantity, reason=StockMovement.WASTAGE, idempotency_key=f"wastage:{wastage.pk}", note=wastage.reason)
        SecurityAuditLog.record(wastage.business, "inventory.wastage", actor=actor, object_type="wastage", object_id=wastage.pk)
