from rest_framework import serializers
from .models import ChatConversation, ChatMessage, ChatMemory


class ChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("system", "user", "assistant"))
    content = serializers.CharField(allow_blank=False, max_length=50000)
    images = serializers.ListField(
        child=serializers.CharField(max_length=1_500_000),
        required=False,
        default=list,
        max_length=4,
    )


class ChatRequestSerializer(serializers.Serializer):
    organization_slug = serializers.SlugField(required=False, allow_blank=False, max_length=180)
    model = serializers.CharField(required=False, allow_blank=False, max_length=256)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    regenerate = serializers.BooleanField(required=False, default=False)
    temporary = serializers.BooleanField(required=False, default=False)
    model_options = serializers.DictField(required=False, default=dict)
    context_options = serializers.DictField(required=False, default=dict)
    messages = ChatMessageSerializer(many=True, allow_empty=False, max_length=100)

    def validate(self, attrs):
        messages = attrs["messages"]
        text_size = sum(len(message["content"]) for message in messages)
        image_size = sum(len(image) for message in messages for image in message.get("images", []))
        if text_size > 200000:
            raise serializers.ValidationError({"messages": "Keep total message text under 200,000 characters."})
        if image_size > 6000000:
            raise serializers.ValidationError({"messages": "Keep total encoded image data under 6,000,000 characters."})
        return attrs

    def validate_context_options(self, value):
        allowed = {"conversation_history", "organization", "organization_profile", "documents", "saved_memory"}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(
                f"Unsupported context option(s): {', '.join(sorted(unknown))}."
            )
        if any(not isinstance(enabled, bool) for enabled in value.values()):
            raise serializers.ValidationError("Context options must be true or false.")
        return value

    def validate_model_options(self, value):
        allowed = {"context_window", "think", "input_mode"}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(
                f"Unsupported model option(s): {', '.join(sorted(unknown))}."
            )
        if "context_window" in value:
            if isinstance(value["context_window"], bool) or not isinstance(value["context_window"], int) or not 128 <= value["context_window"] <= 131072:
                raise serializers.ValidationError("context_window must be an integer between 128 and 131072.")
        if "think" in value and not isinstance(value["think"], bool):
            raise serializers.ValidationError("think must be a boolean.")
        if value.get("input_mode") not in (None, "text", "multimodal"):
            raise serializers.ValidationError("input_mode must be text or multimodal.")
        return value


class MarkdownRenderSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=100000, allow_blank=True)


class ChatMessageHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ("id", "role", "content", "images", "references", "memory_count", "created_at")


class ChatConversationListSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChatConversation
        fields = ("id", "title", "model", "message_count", "created_at", "updated_at")


class ChatConversationDetailSerializer(serializers.ModelSerializer):
    messages = ChatMessageHistorySerializer(many=True, read_only=True)

    class Meta:
        model = ChatConversation
        fields = ("id", "title", "model", "created_at", "updated_at", "messages")


class ChatMemoryPreferenceSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ChatMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMemory
        fields = ("id", "content", "category", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_content(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Memory cannot be blank.")
        if len(value) > 10000:
            raise serializers.ValidationError("Memory corpus cannot exceed 10000 characters.")
        return value

    def validate(self, attrs):
        owner_hash = self.context.get("owner_hash")
        content = attrs.get("content", getattr(self.instance, "content", ""))
        duplicates = ChatMemory.objects.filter(
            owner_hash=owner_hash,
            content__iexact=content,
        )
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if content and duplicates.exists():
            raise serializers.ValidationError({"content": "This memory is already saved."})
        return attrs
