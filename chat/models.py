import uuid
from django.db import models
import hashlib


class ChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_hash = models.CharField(max_length=64, db_index=True)
    organization = models.ForeignKey(
        "organizations.Organization",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="chat_conversations",
    )
    title = models.CharField(max_length=160, default="New conversation")
    model = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    @staticmethod
    def hash_owner(owner_token):
        return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()


class ChatMessage(models.Model):
    ROLE_SYSTEM = "system"
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = (
        (ROLE_SYSTEM, "System"),
        (ROLE_USER, "User"),
        (ROLE_ASSISTANT, "Assistant"),
    )

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    images = models.JSONField(default=list, blank=True)
    references = models.JSONField(default=list, blank=True)
    memory_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ChatMemoryPreference(models.Model):
    owner_hash = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class ChatMemory(models.Model):
    CATEGORY_PREFERENCE = "preference"
    CATEGORY_PROJECT = "project"
    CATEGORY_FACT = "fact"
    CATEGORY_CHOICES = (
        (CATEGORY_PREFERENCE, "Preference"),
        (CATEGORY_PROJECT, "Project"),
        (CATEGORY_FACT, "Fact"),
    )

    owner_hash = models.CharField(max_length=64, db_index=True)
    content = models.TextField()
    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_FACT,
    )
    source_conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memories",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("owner_hash", "content"),
                name="unique_chat_memory_per_owner",
            )
        ]
