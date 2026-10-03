from rest_framework import serializers

from .models import (
    BusinessProfile,
    ChatConversation,
    ChatMemory,
    ChatMessage,
    LocalModelProfile,
    MenuItem,
    Order,
    OrderItem,
)


class ChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("system", "user", "assistant"))
    content = serializers.CharField(allow_blank=False)
    images = serializers.ListField(
        child=serializers.CharField(max_length=1_500_000),
        required=False,
        default=list,
        max_length=4,
    )


class ChatRequestSerializer(serializers.Serializer):
    model = serializers.CharField(required=False, allow_blank=False, max_length=256)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    regenerate = serializers.BooleanField(required=False, default=False)
    model_options = serializers.DictField(required=False, default=dict)
    messages = ChatMessageSerializer(many=True, allow_empty=False)

    def validate_model_options(self, value):
        allowed = {"context_window", "think", "input_mode"}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(
                f"Unsupported model option(s): {', '.join(sorted(unknown))}."
            )
        if "context_window" in value:
            if not isinstance(value["context_window"], int) or not 128 <= value["context_window"] <= 1_000_000:
                raise serializers.ValidationError("context_window must be an integer between 128 and 1000000.")
        if "think" in value and not isinstance(value["think"], bool):
            raise serializers.ValidationError("think must be a boolean.")
        if value.get("input_mode") not in (None, "text", "multimodal"):
            raise serializers.ValidationError("input_mode must be text or multimodal.")
        return value


class LocalModelProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocalModelProfile
        fields = (
            "id",
            "name",
            "context_window",
            "supports_thinking",
            "think_enabled",
            "supports_vision",
            "input_mode",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        if attrs.get("input_mode", getattr(self.instance, "input_mode", "text")) == "multimodal":
            attrs["supports_vision"] = True
        if not attrs.get("supports_thinking", getattr(self.instance, "supports_thinking", False)):
            attrs["think_enabled"] = False
        return attrs


class MarkdownRenderSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=100000, allow_blank=True)


class ChatMessageHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ("id", "role", "content", "images", "memory_count", "created_at")


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


class BusinessProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessProfile
        fields = (
            "business_name",
            "business_type",
            "preferred_provider",
            "cloud_provider",
            "default_model",
            "description",
            "discount_percent",
            "tax_rate",
        )


class BusinessSetupPromptSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=4000, allow_blank=False)

    def validate_prompt(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Describe the business you want to set up.")
        return value


class BusinessCatalogItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    category = serializers.CharField(max_length=100, required=False, default="General")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class BusinessSetupSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=200)
    business_type = serializers.ChoiceField(choices=BusinessProfile.BUSINESS_TYPE_CHOICES)
    description = serializers.CharField(allow_blank=True, default="")
    catalog = BusinessCatalogItemSerializer(many=True, max_length=30)


class MenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = (
            "id",
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )


class MenuItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = (
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )


class OrderItemCreateSerializer(serializers.Serializer):
    menu_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=50)


class OrderItemSerializer(serializers.ModelSerializer):
    menu_item_id = serializers.IntegerField(source="menu_item.id", read_only=True)
    name = serializers.CharField(source="menu_item.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = ("menu_item_id", "name", "quantity", "unit_price", "line_total")


class OrderCreateSerializer(serializers.Serializer):
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = OrderItemCreateSerializer(many=True, allow_empty=False)


class OrderPreviewSerializer(serializers.Serializer):
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = OrderItemCreateSerializer(many=True, allow_empty=False)


class OrderParseSerializer(serializers.Serializer):
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    order_text = serializers.CharField(allow_blank=False)


class ParsedOrderResponseSerializer(serializers.Serializer):
    items = OrderItemCreateSerializer(many=True, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    unmatched_items = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        max_length=30,
    )
    warnings = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        max_length=30,
    )
    questions = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        max_length=30,
    )


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ("status", "fulfillment_status", "payment_status")
        extra_kwargs = {
            "status": {"required": False},
            "fulfillment_status": {"required": False},
            "payment_status": {"required": False},
        }


class OrderQueueFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=("all",) + tuple(status for status, _ in Order.STATUS_CHOICES),
        required=False,
        default="all",
    )


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "customer_name",
            "notes",
            "status",
            "fulfillment_status",
            "payment_status",
            "review_status",
            "review_note",
            "reviewed_by",
            "reviewed_at",
            "subtotal",
            "discount",
            "tax",
            "total",
            "items",
            "created_at",
        )
