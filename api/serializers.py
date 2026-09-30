from rest_framework import serializers

from .models import (
    BusinessProfile,
    ChatConversation,
    ChatMemory,
    ChatMessage,
    MenuItem,
    Order,
    OrderItem,
)


class ChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("system", "user", "assistant"))
    content = serializers.CharField(allow_blank=False)


class ChatRequestSerializer(serializers.Serializer):
    model = serializers.CharField(required=False, allow_blank=False, max_length=256)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    regenerate = serializers.BooleanField(required=False, default=False)
    messages = ChatMessageSerializer(many=True, allow_empty=False)


class MarkdownRenderSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=100000, allow_blank=True)


class ChatMessageHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ("id", "role", "content", "memory_count", "created_at")


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


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ("status",)


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
            "subtotal",
            "discount",
            "tax",
            "total",
            "items",
            "created_at",
        )
