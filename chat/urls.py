from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat, name="chat"),
    path("health/", views.health, name="health"),
    path("models/", views.models, name="models"),
    path("local-model-profiles/", views.local_model_profiles, name="local-model-profiles"),
    path("local-model-profiles/<int:profile_id>/", views.local_model_profile_detail, name="local-model-profile-detail"),
    path("conversations/", views.chat_conversations, name="chat-conversations"),
    path("conversations/<uuid:conversation_id>/", views.chat_conversation_detail, name="chat-conversation-detail"),
    path("memory/", views.chat_memory_preference, name="chat-memory-preference"),
    path("memories/", views.chat_memories, name="chat-memories"),
    path("memories/<int:memory_id>/", views.chat_memory_detail, name="chat-memory-detail"),
    path("markdown/", views.render_markdown, name="render-markdown"),
]
