from django.db import migrations, models
import django.db.models.deletion
import uuid
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [("restaurant", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="PaymentIntent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("status", models.CharField(
                    choices=[("requires_payment_method", "Requires Payment Method"), ("requires_confirmation", "Requires Confirmation"), ("processing", "Processing"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("canceled", "Canceled"), ("refunded", "Refunded")],
                    default="requires_payment_method", max_length=32,
                )),
                ("provider", models.CharField(default="local", max_length=64)),
                ("provider_reference", models.CharField(blank=True, default="", max_length=160)),
                ("idempotency_key", models.CharField(max_length=160)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payment_intents", to="api.businessprofile")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payment_intents", to="api.order")),
            ],
            options={"ordering": ["-created_at"], "constraints": [models.UniqueConstraint(fields=("business", "idempotency_key"), name="unique_payment_idempotency")]},
        ),
        migrations.CreateModel(
            name="PaymentWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=64)),
                ("event_id", models.CharField(max_length=160)),
                ("event_type", models.CharField(max_length=80)),
                ("payload", models.JSONField(default=dict)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("provider", "event_id"), name="unique_payment_webhook_event")]},
        ),
    ]
