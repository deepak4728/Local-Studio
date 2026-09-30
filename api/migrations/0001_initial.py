from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BusinessProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("business_name", models.CharField(default="My Business", max_length=200)),
                (
                    "business_type",
                    models.CharField(
                        choices=[
                            ("generic", "Generic business"),
                            ("restaurant", "Restaurant"),
                        ],
                        default="generic",
                        max_length=32,
                    ),
                ),
                (
                    "preferred_provider",
                    models.CharField(
                        choices=[("local", "Local Ollama"), ("cloud", "Cloud API")],
                        default="local",
                        max_length=16,
                    ),
                ),
                ("cloud_provider", models.CharField(blank=True, default="", max_length=50)),
                ("default_model", models.CharField(blank=True, default="", max_length=128)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
