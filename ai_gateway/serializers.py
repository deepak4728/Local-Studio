from rest_framework import serializers
from .models import LocalModelProfile, AIConfiguration


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


class AIConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIConfiguration
        fields = ("preferred_provider", "cloud_provider", "default_model")
