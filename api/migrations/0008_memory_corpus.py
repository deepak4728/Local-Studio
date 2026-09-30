from django.db import migrations, models


def merge_memory_rows(apps, schema_editor):
    ChatMemory = apps.get_model("api", "ChatMemory")
    for owner_hash in ChatMemory.objects.values_list("owner_hash", flat=True).distinct():
        rows = list(ChatMemory.objects.filter(owner_hash=owner_hash).order_by("created_at", "id"))
        if len(rows) < 2:
            continue
        primary = rows[0]
        content = "\n\n".join(row.content.strip() for row in rows if row.content.strip())
        primary.content = content[:10000]
        primary.save(update_fields=["content", "updated_at"])
        ChatMemory.objects.filter(pk__in=[row.pk for row in rows[1:]]).delete()


class Migration(migrations.Migration):
    dependencies = [("api", "0007_chatmessage_images")]

    operations = [
        migrations.AlterField(
            model_name="chatmemory",
            name="content",
            field=models.TextField(),
        ),
        migrations.RunPython(merge_memory_rows, migrations.RunPython.noop),
    ]
