from io import BytesIO
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from asgiref.sync import async_to_sync
from django.test import AsyncClient, override_settings
from rest_framework.test import APITestCase

from api.models import (
    BusinessProfile,
    ChatConversation,
    ChatMemory,
    ChatMemoryPreference,
    ChatMessage,
    MenuItem,
    Order,
    OrderItem,
)


@override_settings(API_KEY="test-api-key", OLLAMA_DEFAULT_MODEL="test-model")
class OllamaAPITests(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_API_KEY="test-api-key")

    def test_chat_interface_loads_without_exposing_configured_api_key(self):
        self.client.credentials()
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Studio")
        self.assertContains(response, "test-model")
        self.assertNotContains(response, "test-api-key")

    def test_missing_api_key_is_rejected(self):
        self.client.credentials()

        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "The X-API-Key header is required.")

    def test_invalid_api_key_is_rejected(self):
        self.client.credentials(HTTP_X_API_KEY="wrong-key")

        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "The API key is invalid.")

    @override_settings(API_KEY="")
    def test_unconfigured_api_key_fails_closed(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 503)

    @patch("api.views.get_ollama_models", return_value=[])
    def test_health_checks_ollama(self, get_models):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"status": "ok", "ollama": "available"})
        get_models.assert_called_once_with()

    @patch("api.views.get_ollama_models", return_value=[{"name": "test-model"}])
    def test_models_returns_available_models(self, get_models):
        response = self.client.get("/api/models/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"models": [{"name": "test-model"}]})
        get_models.assert_called_once_with()

    def test_chat_requires_messages(self):
        response = self.client.post("/api/chat/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("messages", response.data)

    def test_chat_rejects_invalid_message_role(self):
        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "tool", "content": "Hello"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("messages", response.data)

    @patch("api.views.open_ollama_response")
    def test_chat_streams_ollama_ndjson_and_uses_default_model(self, open_response):
        chunks = (
            b'{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
            b'{"message":{"role":"assistant","content":"!"},"done":true}\n'
        )
        upstream = BytesIO(chunks)
        open_response.return_value = upstream

        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "Say hello"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-ndjson")
        self.assertEqual(b"".join(response.streaming_content), chunks)
        self.assertTrue(upstream.closed)

        request_payload = open_response.call_args.args[1]
        self.assertEqual(
            request_payload,
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Say hello"}],
                "stream": True,
            },
        )

    @patch("api.views.open_ollama_response")
    def test_chat_persists_streamed_messages_and_returns_conversation_id(self, open_response):
        chunks = (
            b'{"message":{"role":"assistant","content":"Saved"},"done":false}\n'
            b'{"message":{"role":"assistant","content":" response"},"done":true}\n'
        )
        open_response.return_value = BytesIO(chunks)

        response = self.client.post(
            "/api/chat/",
            {
                "messages": [{"role": "user", "content": "Remember this chat"}],
            },
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, chunks)
        conversation_id = response["X-Conversation-ID"]
        conversation = ChatConversation.objects.get(pk=conversation_id)
        self.assertEqual(conversation.title, "Remember this chat")
        self.assertEqual(
            list(conversation.messages.values_list("role", "content")),
            [
                (ChatMessage.ROLE_USER, "Remember this chat"),
                (ChatMessage.ROLE_ASSISTANT, "Saved response"),
            ],
        )

    @patch("api.views.open_ollama_response")
    def test_chat_continues_existing_conversation_from_database(self, open_response):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Existing chat",
            model="test-model",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content="Earlier question",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_ASSISTANT,
            content="Earlier answer",
        )
        open_response.return_value = BytesIO(
            b'{"message":{"role":"assistant","content":"Next answer"},"done":true}\n'
        )

        response = self.client.post(
            "/api/chat/",
            {
                "conversation_id": str(conversation.id),
                "messages": [{"role": "user", "content": "Next question"}],
            },
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body)
        self.assertEqual(response["X-Conversation-ID"], str(conversation.id))
        request_messages = open_response.call_args.args[1]["messages"]
        self.assertEqual(
            request_messages,
            [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
                {"role": "user", "content": "Next question"},
            ],
        )
        self.assertEqual(conversation.messages.count(), 4)

    @patch("api.views.open_ollama_response")
    def test_regenerate_replaces_only_the_latest_assistant_reply(self, open_response):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Existing chat",
            model="test-model",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content="Explain the plan",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_ASSISTANT,
            content="First answer",
        )
        open_response.return_value = BytesIO(
            b'{"message":{"role":"assistant","content":"Replacement"},"done":true}\n'
        )

        response = self.client.post(
            "/api/chat/",
            {
                "conversation_id": str(conversation.id),
                "regenerate": True,
                "messages": [{"role": "user", "content": "Explain the plan"}],
            },
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body)
        self.assertEqual(
            list(conversation.messages.values_list("role", "content")),
            [
                (ChatMessage.ROLE_USER, "Explain the plan"),
                (ChatMessage.ROLE_ASSISTANT, "Replacement"),
            ],
        )
        self.assertEqual(
            open_response.call_args.args[1]["messages"],
            [{"role": "user", "content": "Explain the plan"}],
        )

    @patch(
        "api.views.open_ollama_response",
        side_effect=HTTPError("http://localhost/api/chat", 500, "Failure", {}, None),
    )
    def test_failed_regeneration_keeps_the_previous_answer(self, open_response):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Existing chat",
            model="test-model",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content="Explain the plan",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_ASSISTANT,
            content="First answer",
        )

        response = self.client.post(
            "/api/chat/",
            {
                "conversation_id": str(conversation.id),
                "regenerate": True,
                "messages": [{"role": "user", "content": "Explain the plan"}],
            },
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            list(conversation.messages.values_list("role", "content")),
            [
                (ChatMessage.ROLE_USER, "Explain the plan"),
                (ChatMessage.ROLE_ASSISTANT, "First answer"),
            ],
        )
        open_response.assert_called_once()

    def test_markdown_rendering_formats_text_and_strips_unsafe_markup(self):
        response = self.client.post(
            "/api/markdown/",
            {
                "text": (
                    "# Heading\n\n**Important**\n\n<script>alert(1)</script>\n\n"
                    "[unsafe](javascript:alert(1))"
                )
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Heading</h1>", response.data["html"])
        self.assertIn("<strong>Important</strong>", response.data["html"])
        self.assertNotIn("<script", response.data["html"])
        self.assertNotIn('href="javascript:', response.data["html"])

    def test_conversation_history_is_scoped_to_owner_token(self):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Private history",
        )
        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-b",
        )

        list_response = self.client.get("/api/conversations/")
        detail_response = self.client.get(f"/api/conversations/{conversation.id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data, [])
        self.assertEqual(detail_response.status_code, 404)

    def test_memory_is_off_by_default_and_preferences_are_owner_scoped(self):
        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-a",
        )

        response = self.client.get("/api/memory/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"enabled": False, "memory_count": 0})
        enabled_response = self.client.patch(
            "/api/memory/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(enabled_response.data["enabled"], True)

        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-b",
        )
        other_owner_response = self.client.get("/api/memory/")
        self.assertEqual(other_owner_response.data["enabled"], False)

    def test_memories_can_be_reviewed_edited_and_deleted_only_by_owner(self):
        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        created = self.client.post(
            "/api/memories/",
            {"content": "Prefers concise answers", "category": "preference"},
            format="json",
        )

        self.assertEqual(created.status_code, 201)
        memory_id = created.data["id"]
        self.assertEqual(self.client.get("/api/memories/").data[0]["content"], "Prefers concise answers")
        duplicate = self.client.post(
            "/api/memories/",
            {"content": "prefers concise answers", "category": "preference"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        other_memory = self.client.post(
            "/api/memories/",
            {"content": "Building a local chat app", "category": "project"},
            format="json",
        )
        self.assertEqual(other_memory.status_code, 201)

        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-b",
        )
        forbidden = self.client.patch(
            f"/api/memories/{memory_id}/",
            {"content": "Changed by someone else"},
            format="json",
        )
        self.assertEqual(forbidden.status_code, 404)

        self.client.credentials(
            HTTP_X_API_KEY="test-api-key",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        updated = self.client.patch(
            f"/api/memories/{memory_id}/",
            {"content": "Building a local chat app"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["content"], "Building a local chat app")
        updated = self.client.patch(
            f"/api/memories/{memory_id}/",
            {"content": "Prefers short, direct answers"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["content"], "Prefers short, direct answers")
        deleted = self.client.delete(f"/api/memories/{memory_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.client.delete(f"/api/memories/{other_memory.data['id']}/")
        self.assertEqual(self.client.get("/api/memories/").data, [])

    @patch("api.views._schedule_memory_update")
    @patch("api.views.open_ollama_response")
    def test_enabled_memories_are_injected_into_chat_context(
        self,
        open_response,
        schedule_memory_update,
    ):
        owner_hash = ChatConversation.hash_owner("browser-a")
        ChatMemoryPreference.objects.create(owner_hash=owner_hash, enabled=True)
        ChatMemory.objects.create(
            owner_hash=owner_hash,
            content="The user is building a restaurant ordering app.",
            category=ChatMemory.CATEGORY_PROJECT,
        )
        open_response.return_value = BytesIO(
            b'{"message":{"role":"assistant","content":"Got it."},"done":true}\n'
        )

        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "What am I building?"}]},
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Memory-Count"], "1")
        sent_messages = open_response.call_args.args[1]["messages"]
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertIn("restaurant ordering app", sent_messages[0]["content"])
        self.assertEqual(
            ChatMessage.objects.filter(role=ChatMessage.ROLE_ASSISTANT).get().memory_count,
            1,
        )

    @patch("api.views._schedule_memory_update")
    @patch("api.views.open_ollama_response")
    def test_manually_saved_memory_is_used_while_auto_updates_are_off(
        self,
        open_response,
        schedule_memory_update,
    ):
        owner_hash = ChatConversation.hash_owner("browser-a")
        ChatMemory.objects.create(
            owner_hash=owner_hash,
            content="The user prefers direct answers.",
            category=ChatMemory.CATEGORY_PREFERENCE,
        )
        open_response.return_value = BytesIO(
            b'{"message":{"role":"assistant","content":"Understood."},"done":true}\n'
        )

        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "How should you answer?"}]},
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )
        b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Memory-Count"], "1")
        self.assertIn(
            "prefers direct answers",
            open_response.call_args.args[1]["messages"][0]["content"],
        )

    def test_memory_extraction_is_disabled_until_user_opts_in(self):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Project detail",
            model="test-model",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content="I'm building a restaurant ordering app.",
        )

        with patch("api.views.open_ollama_response") as open_response:
            from api.views import _extract_and_save_memories

            _extract_and_save_memories(
                conversation.owner_hash,
                conversation.id,
                conversation.model,
            )

        open_response.assert_not_called()
        self.assertEqual(ChatMemory.objects.count(), 0)

    def test_enabled_memory_extraction_saves_compact_facts(self):
        conversation = ChatConversation.objects.create(
            owner_hash=ChatConversation.hash_owner("browser-a"),
            title="Project detail",
            model="test-model",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content="I'm building a restaurant ordering app and prefer concise answers.",
        )
        ChatMemoryPreference.objects.create(owner_hash=conversation.owner_hash, enabled=True)
        extraction_response = BytesIO(
            b'{"message":{"content":"{\\"memories\\":[{\\"content\\":\\"Building a restaurant ordering app\\",\\"category\\":\\"project\\"}]}"}}'
        )

        with patch("api.views.open_ollama_response", return_value=extraction_response) as open_response:
            from api.views import _extract_and_save_memories

            _extract_and_save_memories(
                conversation.owner_hash,
                conversation.id,
                conversation.model,
            )

        self.assertEqual(ChatMemory.objects.count(), 1)
        memory = ChatMemory.objects.get()
        self.assertEqual(memory.content, "Building a restaurant ordering app")
        self.assertEqual(memory.category, ChatMemory.CATEGORY_PROJECT)
        self.assertEqual(memory.source_conversation, conversation)
        payload = open_response.call_args.args[1]
        self.assertFalse(payload["stream"])
        self.assertIn("Do not store secrets", payload["messages"][0]["content"])

    @patch("api.views.open_ollama_response")
    def test_chat_streams_ollama_ndjson_over_asgi(self, open_response):
        chunks = (
            b'{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
            b'{"message":{"role":"assistant","content":"!"},"done":true}\n'
        )
        upstream = BytesIO(chunks)
        open_response.return_value = upstream

        async def send_request():
            client = AsyncClient()
            response = await client.post(
                "/api/chat/",
                data='{"messages":[{"role":"user","content":"Say hello"}]}',
                content_type="application/json",
                headers={"X-API-Key": "test-api-key"},
            )
            self.assertEqual(response.status_code, 200, getattr(response, "data", None))
            body = b"".join(
                [chunk async for chunk in response.streaming_content]
            )
            return response, body

        response, body = async_to_sync(send_request)()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-ndjson")
        self.assertEqual(body, chunks)
        self.assertTrue(upstream.closed)

    @patch(
        "api.views.open_ollama_response",
        side_effect=HTTPError(
            "http://127.0.0.1:11434/api/chat",
            404,
            "Not Found",
            {},
            None,
        ),
    )
    def test_ollama_http_errors_are_reported_as_bad_gateway(self, open_response):
        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "Hello"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["ollama_status"], 404)
        open_response.assert_called_once()

    @patch("api.views.open_ollama_response", side_effect=URLError("connection refused"))
    def test_unreachable_ollama_is_reported_as_service_unavailable(self, open_response):
        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "Hello"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], "Unable to connect to Ollama.")
        open_response.assert_called_once()


@override_settings(
    API_KEY="test-api-key",
    OLLAMA_DEFAULT_MODEL="test-local-model",
    CLOUD_API_KEY="server-cloud-key",
    CLOUD_API_BASE_URL="https://cloud.example/v1",
)
class CloudProviderAPITests(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_API_KEY="test-api-key")
        self.profile = BusinessProfile.get_or_create_default()
        self.profile.preferred_provider = BusinessProfile.PROVIDER_CLOUD
        self.profile.cloud_provider = "openai-compatible"
        self.profile.default_model = "cloud-chat-model"
        self.profile.save()

    def test_cloud_health_and_models_use_configured_model_without_calling_ollama(self):
        with patch("api.views.get_ollama_models") as get_models:
            health_response = self.client.get("/api/health/")
            models_response = self.client.get("/api/models/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.data, {"status": "ok", "provider": "cloud"})
        self.assertEqual(models_response.data, {"models": [{"name": "cloud-chat-model"}]})
        get_models.assert_not_called()

    @patch("api.providers.urlopen")
    def test_cloud_chat_routes_to_endpoint_and_normalizes_response(self, open_url):
        open_url.return_value = BytesIO(
            json.dumps(
                {"choices": [{"message": {"content": "Cloud reply"}}]}
            ).encode("utf-8")
        )

        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "Say hello"}]},
            format="json",
        )
        body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-ndjson")
        self.assertIn(b'"content": "Cloud reply"', body)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://cloud.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer server-cloud-key")
        self.assertEqual(json.loads(request.data)["model"], "cloud-chat-model")
        self.assertNotIn(b"server-cloud-key", body)

    @override_settings(CLOUD_API_KEY="")
    def test_cloud_provider_fails_clearly_without_server_key(self):
        response = self.client.get("/api/models/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("Set CLOUD_API_KEY", response.data["detail"])


@override_settings(
    API_KEY="test-api-key",
    STAFF_API_KEY="staff-test-key",
    OLLAMA_DEFAULT_MODEL="test-model",
)
class BusinessProfileAPITests(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_API_KEY="test-api-key")

    def test_business_profile_defaults_to_local_provider(self):
        response = self.client.get("/api/business/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["preferred_provider"], "local")
        self.assertEqual(response.data["default_model"], "test-model")
        self.assertEqual(response.data["business_type"], "generic")

    def test_business_profile_can_be_updated(self):
        response = self.client.post(
            "/api/business/profile/",
            {
                "business_name": "Café Luna",
                "business_type": "restaurant",
                "preferred_provider": "cloud",
                "cloud_provider": "openai",
                "default_model": "gpt-4o-mini",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["business_name"], "Café Luna")
        self.assertEqual(response.data["preferred_provider"], "cloud")

        profile = BusinessProfile.objects.get()
        self.assertEqual(profile.business_name, "Café Luna")
        self.assertEqual(profile.preferred_provider, "cloud")
        self.assertEqual(profile.cloud_provider, "openai")

    def test_business_profile_can_be_loaded_and_updated_with_staff_key(self):
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        get_response = self.client.get("/api/business/profile/")
        post_response = self.client.post(
            "/api/business/profile/",
            {"business_name": "Staff-managed business"},
            format="json",
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.data["business_name"], "Staff-managed business")

    @patch("api.views.open_ollama_response")
    def test_business_setup_draft_uses_local_model_without_saving(self, open_response):
        open_response.return_value = BytesIO(
            b'{"message":{"content":"{\\"business_name\\":\\"Corner Cafe\\",'
            b'\\"business_type\\":\\"generic\\",\\"description\\":\\"Coffee and pastries\\",'
            b'\\"catalog\\":[{\\"name\\":\\"Coffee\\",\\"category\\":\\"Drinks\\",'
            b'\\"description\\":\\"House coffee\\",\\"price\\":\\"4.50\\"}]}"}}'
        )
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        response = self.client.post(
            "/api/business/draft/",
            {"prompt": "A neighborhood cafe with coffee and pastries"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["business_name"], "Corner Cafe")
        self.assertEqual(response.data["catalog"][0]["price"], "4.50")
        self.assertEqual(BusinessProfile.objects.get().business_name, "My Business")
        self.assertFalse(MenuItem.objects.exists())
        self.assertEqual(open_response.call_args.args[1]["model"], "test-model")

    def test_business_setup_requires_owner_reviewed_valid_data(self):
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        response = self.client.post(
            "/api/business/setup/",
            {
                "business_name": "Corner Cafe",
                "business_type": "generic",
                "description": "Coffee and pastries",
                "catalog": [
                    {
                        "name": "Coffee",
                        "category": "Drinks",
                        "description": "House coffee",
                        "price": "4.50",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(BusinessProfile.objects.get().business_name, "Corner Cafe")
        self.assertEqual(MenuItem.objects.get().name, "Coffee")

    @patch("api.views.open_ollama_response")
    def test_business_setup_draft_rejects_cloud_provider(self, open_response):
        profile = BusinessProfile.get_or_create_default()
        profile.preferred_provider = BusinessProfile.PROVIDER_CLOUD
        profile.save()
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        response = self.client.post(
            "/api/business/draft/",
            {"prompt": "A cafe"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        open_response.assert_not_called()

    def test_menu_and_order_workflow_for_restaurant(self):
        profile = BusinessProfile.get_or_create_default()
        profile.business_type = BusinessProfile.BUSINESS_TYPE_RESTAURANT
        profile.save()

        burger = MenuItem.objects.create(
            name="Classic Burger",
            category="Mains",
            description="Grilled beef burger",
            price="12.50",
            is_available=True,
        )
        drink = MenuItem.objects.create(
            name="Lemon Tea",
            category="Drinks",
            description="Fresh brewed tea",
            price="3.00",
            is_available=True,
        )

        menu_response = self.client.get("/api/menu/")
        self.assertEqual(menu_response.status_code, 200)
        self.assertEqual(len(menu_response.data), 2)

        order_response = self.client.post(
            "/api/orders/",
            {
                "customer_name": "Alice",
                "items": [
                    {"menu_item_id": burger.id, "quantity": 2},
                    {"menu_item_id": drink.id, "quantity": 1},
                ],
            },
            format="json",
        )

        self.assertEqual(order_response.status_code, 200)
        self.assertEqual(order_response.data["customer_name"], "Alice")
        self.assertEqual(order_response.data["subtotal"], "28.00")
        self.assertEqual(order_response.data["total"], "28.00")

        order = Order.objects.get(pk=order_response.data["id"])
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.status, Order.STATUS_PENDING)

    def test_menu_can_be_created_and_order_status_can_be_updated(self):
        profile = BusinessProfile.get_or_create_default()
        profile.business_type = BusinessProfile.BUSINESS_TYPE_RESTAURANT
        profile.save()

        create_menu_response = self.client.post(
            "/api/menu/",
            {
                "name": "Veg Wrap",
                "category": "Mains",
                "description": "Fresh vegetables and sauces",
                "price": "9.50",
                "is_available": True,
            },
            format="json",
        )

        self.assertEqual(create_menu_response.status_code, 201)
        self.assertEqual(create_menu_response.data["name"], "Veg Wrap")

        menu_item = MenuItem.objects.get(name="Veg Wrap")
        order = Order.objects.create(
            business=profile,
            customer_name="Sam",
            subtotal="9.50",
            total="9.50",
        )
        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            quantity=1,
            unit_price=menu_item.price,
        )

        status_response = self.client.patch(
            f"/api/orders/{order.id}/status/",
            {"status": Order.STATUS_PREPARING},
            format="json",
        )

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.data["status"], Order.STATUS_PREPARING)
        self.assertEqual(Order.objects.get(pk=order.id).status, Order.STATUS_PREPARING)

    def test_menu_can_be_loaded_and_created_with_staff_key(self):
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        get_response = self.client.get("/api/menu/")
        post_response = self.client.post(
            "/api/menu/",
            {
                "name": "Staff-added soup",
                "category": "Mains",
                "price": "8.50",
            },
            format="json",
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 201)
        self.assertEqual(post_response.data["name"], "Staff-added soup")

    def test_order_preview_and_kitchen_queue(self):
        profile = BusinessProfile.get_or_create_default()
        profile.business_type = BusinessProfile.BUSINESS_TYPE_RESTAURANT
        profile.save()

        burger = MenuItem.objects.create(
            name="Classic Burger",
            category="Mains",
            description="Grilled beef burger",
            price="12.50",
            is_available=True,
        )
        tea = MenuItem.objects.create(
            name="Lemon Tea",
            category="Drinks",
            description="Fresh brewed tea",
            price="3.00",
            is_available=True,
        )

        preview_response = self.client.post(
            "/api/orders/preview/",
            {
                "customer_name": "Nina",
                "items": [
                    {"menu_item_id": burger.id, "quantity": 2},
                    {"menu_item_id": tea.id, "quantity": 1},
                ],
            },
            format="json",
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.data["customer_name"], "Nina")
        self.assertEqual(preview_response.data["total"], "28.00")

        submit_response = self.client.post(
            "/api/orders/",
            {
                "customer_name": "Nina",
                "items": [
                    {"menu_item_id": burger.id, "quantity": 2},
                    {"menu_item_id": tea.id, "quantity": 1},
                ],
            },
            format="json",
        )

        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(submit_response.data["status"], Order.STATUS_PENDING)

        queue_response = self.client.get("/api/orders/queue/")
        self.assertEqual(queue_response.status_code, 200)
        self.assertTrue(any(item["customer_name"] == "Nina" for item in queue_response.data))

    def test_order_preview_uses_configured_discount_and_tax(self):
        profile = BusinessProfile.get_or_create_default()
        profile.discount_percent = "5.00"
        profile.tax_rate = "10.00"
        profile.save()
        burger = MenuItem.objects.create(name="Burger", price="20.00")

        response = self.client.post(
            "/api/orders/preview/",
            {
                "items": [{"menu_item_id": burger.id, "quantity": 2}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subtotal"], "40.00")
        self.assertEqual(response.data["discount"], "2.00")
        self.assertEqual(response.data["tax"], "4.00")
        self.assertEqual(response.data["total"], "42.00")

        order_response = self.client.post(
            "/api/orders/",
            {"items": [{"menu_item_id": burger.id, "quantity": 2}]},
            format="json",
        )

        self.assertEqual(order_response.status_code, 200)
        self.assertEqual(order_response.data["subtotal"], response.data["subtotal"])
        self.assertEqual(order_response.data["discount"], response.data["discount"])
        self.assertEqual(order_response.data["tax"], response.data["tax"])
        self.assertEqual(order_response.data["total"], response.data["total"])


@override_settings(API_KEY="test-api-key", OLLAMA_DEFAULT_MODEL="test-model", STAFF_API_KEY="staff-test-key")
class StaffDashboardAPITests(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_API_KEY="test-api-key")

    def test_staff_dashboard_page_is_available(self):
        response = self.client.get("/staff/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Dashboard")
        self.assertContains(response, 'id="order-status-filter"')
        self.assertContains(response, 'id="order-detail-dialog"')

    def test_customer_order_page_is_available(self):
        response = self.client.get("/order/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Place Order")

    def test_staff_menu_page_is_available(self):
        response = self.client.get("/staff/menu/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menu Management")

    def test_business_settings_page_is_available(self):
        response = self.client.get("/staff/settings/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Business Settings")

    def test_staff_dashboard_requires_staff_key(self):
        response = self.client.get("/api/staff/dashboard/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "The X-Staff-Key header is required.")

    def test_staff_dashboard_returns_order_summary(self):
        profile = BusinessProfile.get_or_create_default()
        profile.business_type = BusinessProfile.BUSINESS_TYPE_RESTAURANT
        profile.save()

        menu_item = MenuItem.objects.create(
            name="Classic Burger",
            category="Mains",
            description="Grilled beef burger",
            price="12.50",
            is_available=True,
        )

        active_order = Order.objects.create(
            business=profile,
            customer_name="Dana",
            status=Order.STATUS_PENDING,
            subtotal="12.50",
            total="12.50",
        )
        OrderItem.objects.create(
            order=active_order,
            menu_item=menu_item,
            quantity=1,
            unit_price=menu_item.price,
        )

        completed_order = Order.objects.create(
            business=profile,
            customer_name="Evan",
            status=Order.STATUS_COMPLETED,
            subtotal="25.00",
            total="25.00",
        )

        response = self.client.get(
            "/api/staff/dashboard/",
            HTTP_X_STAFF_KEY="staff-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pending_orders"], 1)
        self.assertEqual(response.data["completed_orders"], 1)
        self.assertEqual(response.data["total_revenue"], "37.50")

    def test_order_queue_can_filter_by_status_and_defaults_to_active_orders(self):
        profile = BusinessProfile.get_or_create_default()
        pending = Order.objects.create(business=profile, status=Order.STATUS_PENDING)
        completed = Order.objects.create(business=profile, status=Order.STATUS_COMPLETED)
        Order.objects.create(business=profile, status=Order.STATUS_CANCELLED)

        default_response = self.client.get("/api/orders/queue/")
        completed_response = self.client.get("/api/orders/queue/?status=completed")
        invalid_response = self.client.get("/api/orders/queue/?status=unknown")

        self.assertEqual(default_response.status_code, 200)
        self.assertEqual({order["id"] for order in default_response.data}, {pending.id, completed.id})
        self.assertEqual(completed_response.status_code, 200)
        self.assertEqual([order["id"] for order in completed_response.data], [completed.id])
        self.assertEqual(invalid_response.status_code, 400)

    def test_order_detail_returns_items_and_requires_staff_or_api_key(self):
        profile = BusinessProfile.get_or_create_default()
        menu_item = MenuItem.objects.create(
            name="House Salad",
            category="Sides",
            price="6.50",
        )
        order = Order.objects.create(
            business=profile,
            customer_name="Mina",
            notes="No onions",
            subtotal="13.00",
            total="13.00",
        )
        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            quantity=2,
            unit_price=menu_item.price,
        )

        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")
        response = self.client.get(f"/api/orders/{order.id}/")
        self.client.credentials()
        unauthenticated_response = self.client.get(f"/api/orders/{order.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["customer_name"], "Mina")
        self.assertEqual(response.data["notes"], "No onions")
        self.assertEqual(response.data["items"][0]["name"], "House Salad")
        self.assertEqual(response.data["items"][0]["line_total"], "13.00")
        self.assertEqual(unauthenticated_response.status_code, 401)

    def test_order_detail_does_not_expose_another_business_order(self):
        profile = BusinessProfile.get_or_create_default()
        other_business = BusinessProfile.objects.create(business_name="Other business")
        order = Order.objects.create(business=other_business)

        response = self.client.get(f"/api/orders/{order.id}/")

        self.assertEqual(response.status_code, 404)

    def test_staff_key_can_update_order_status(self):
        profile = BusinessProfile.get_or_create_default()
        order = Order.objects.create(business=profile)
        self.client.credentials(HTTP_X_STAFF_KEY="staff-test-key")

        response = self.client.patch(
            f"/api/orders/{order.id}/status/",
            {"status": Order.STATUS_COMPLETED},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Order.STATUS_COMPLETED)


@override_settings(API_KEY="test-api-key", OLLAMA_DEFAULT_MODEL="test-model")
class OrderParsingAPITests(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_API_KEY="test-api-key")
        self.profile = BusinessProfile.get_or_create_default()
        self.profile.business_type = BusinessProfile.BUSINESS_TYPE_RESTAURANT
        self.profile.save()

        self.burger = MenuItem.objects.create(
            name="Classic Burger",
            category="Mains",
            description="Grilled beef burger",
            price="12.50",
            is_available=True,
        )
        self.tea = MenuItem.objects.create(
            name="Lemon Tea",
            category="Drinks",
            description="Fresh brewed tea",
            price="3.00",
            is_available=True,
        )

    @patch("api.views.open_ollama_response")
    def test_order_text_is_parsed_into_structured_items(self, open_response):
        open_response.return_value = BytesIO(
            json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "items": [
                                    {"menu_item_id": self.burger.id, "quantity": 2},
                                    {"menu_item_id": self.tea.id, "quantity": 1},
                                ],
                                "notes": "No onions on one burger",
                                "unmatched_items": [],
                            }
                        )
                    }
                }
            ).encode("utf-8")
        )
        response = self.client.post(
            "/api/orders/parse/",
            {"order_text": "I want 2 classic burgers and 1 lemon tea please"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subtotal"], "28.00")
        self.assertEqual(response.data["items"][0]["menu_item_id"], self.burger.id)
        self.assertEqual(response.data["items"][0]["quantity"], 2)
        self.assertEqual(response.data["items"][1]["menu_item_id"], self.tea.id)
        self.assertEqual(response.data["items"][1]["quantity"], 1)
        self.assertEqual(response.data["notes"], "No onions on one burger")
        self.assertIn("menu", open_response.call_args.args[1]["messages"][1]["content"])

    @patch("api.views.open_ollama_response")
    def test_unmatched_order_text_returns_clear_guidance(self, open_response):
        open_response.return_value = BytesIO(
            json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {"items": [], "unmatched_items": ["mystery dish"]}
                        )
                    }
                }
            ).encode("utf-8")
        )
        response = self.client.post(
            "/api/orders/parse/",
            {"order_text": "I want a mystery dish"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"], [])
        self.assertEqual(response.data["unmatched_items"], ["mystery dish"])

    @patch("api.views.open_ollama_response")
    def test_order_parser_rejects_model_item_ids_not_in_available_menu(self, open_response):
        open_response.return_value = BytesIO(
            json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {"items": [{"menu_item_id": 999, "quantity": 1}], "unmatched_items": []}
                        )
                    }
                }
            ).encode("utf-8")
        )

        response = self.client.post(
            "/api/orders/parse/",
            {"order_text": "one mystery dish"},
            format="json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["detail"], "Ollama returned an item that is not on the available menu.")
