"""Chat HTTP handlers extracted from the legacy API module."""
from api.views import (
    chat, chat_conversation_detail, chat_conversations, chat_interface,
    chat_memories, chat_memory_detail, chat_memory_preference, health,
    local_model_profile_detail, local_model_profiles,
    models, render_markdown,
)

# Keep the public handler name used by the legacy URL configuration.
__all__ = [
    "chat", "chat_conversation_detail", "chat_conversations", "chat_interface",
    "chat_memories", "chat_memory_detail", "chat_memory_preference", "health",
    "local_model_profile_detail", "local_model_profiles", "models", "render_markdown",
]
