import decimal
from django.db import migrations, models
import django.db.models.deletion


def add_default_discount_and_tax(apps, schema_editor):
    BusinessProfile = apps.get_model("api", "BusinessProfile")
    for profile in BusinessProfile.objects.all():
        profile.discount_percent = decimal.Decimal("0.00")
        profile.tax_rate = decimal.Decimal("0.00")
        profile.save(update_fields=["discount_percent", "tax_rate"])


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessprofile",
            name="discount_percent",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=5),
        ),
        migrations.AddField(
            model_name="businessprofile",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=5),
        ),
        migrations.CreateModel(
            name="MenuItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("category", models.CharField(default="General", max_length=100)),
                ("description", models.TextField(blank=True, default="")),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("is_available", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["category", "name"]},
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_name", models.CharField(blank=True, default="", max_length=200)),
                ("notes", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("preparing", "Preparing"), ("ready", "Ready"), ("completed", "Completed"), ("cancelled", "Cancelled")], default="pending", max_length=32)),
                ("subtotal", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10)),
                ("discount", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10)),
                ("tax", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10)),
                ("total", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="orders", to="api.businessprofile")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("line_total", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10)),
                ("menu_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="order_items", to="api.menuitem")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="api.order")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.RunPython(add_default_discount_and_tax, migrations.RunPython.noop),
    ]
