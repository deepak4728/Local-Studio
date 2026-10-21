from io import BytesIO
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import AsyncClient, override_settings
from rest_framework.test import APITestCase
from ai_gateway.models import AIConfiguration
from chat.models import ChatConversation, ChatMemory, ChatMemoryPreference, ChatMessage


@override_settings(
    OLLAMA_DEFAULT_MODEL="test-model",
)
class OllamaAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="chat-user", password="test-password-123"
        )
        self.client.force_login(self.user)

    def test_public_home_loads_without_api_key_configuration(self):
        self.client.logout()
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OrgForms")
        self.assertContains(response, "Sign in")

    def test_api_requires_a_signed_in_session(self):
        self.client.logout()
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 403)

    @patch("ai_gateway.views.get_ollama_models", return_value=[])
    def test_health_checks_ollama(self, get_models):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"status": "ok", "ollama": "available"})
        get_models.assert_called_once_with()

    @patch("ai_gateway.views.get_ollama_models", return_value=[{"name": "test-model"}])
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

    @patch("chat.views.open_ollama_response")
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
            HTTP_X_CHAT_OWNER="browser-a",
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

    @patch("chat.views.open_ollama_response")
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

    @patch("chat.views.open_ollama_response")
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

    @patch("chat.views.open_ollama_response")
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
        "chat.views.open_ollama_response",
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
            HTTP_X_CHAT_OWNER="browser-b",
        )

        list_response = self.client.get("/api/conversations/")
        detail_response = self.client.get(f"/api/conversations/{conversation.id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data, [])
        self.assertEqual(detail_response.status_code, 404)

    def test_memory_is_off_by_default_and_preferences_are_owner_scoped(self):
        self.client.credentials(
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
            HTTP_X_CHAT_OWNER="browser-b",
        )
        other_owner_response = self.client.get("/api/memory/")
        self.assertEqual(other_owner_response.data["enabled"], False)

    def test_memories_can_be_reviewed_edited_and_deleted_only_by_owner(self):
        self.client.credentials(
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
            HTTP_X_CHAT_OWNER="browser-b",
        )
        forbidden = self.client.patch(
            f"/api/memories/{memory_id}/",
            {"content": "Changed by someone else"},
            format="json",
        )
        self.assertEqual(forbidden.status_code, 404)

        self.client.credentials(
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

    @patch("chat.views._schedule_memory_update")
    @patch("chat.views.open_ollama_response")
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

    @patch("chat.views._schedule_memory_update")
    @patch("chat.views.open_ollama_response")
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

        with patch("chat.views.open_ollama_response") as open_response:
            from chat.views import _extract_and_save_memories

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

        with patch("chat.views.open_ollama_response", return_value=extraction_response) as open_response:
            from chat.views import _extract_and_save_memories

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

    @patch("chat.views.open_ollama_response")
    def test_chat_streams_ollama_ndjson_over_asgi(self, open_response):
        chunks = (
            b'{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
            b'{"message":{"role":"assistant","content":"!"},"done":true}\n'
        )
        upstream = BytesIO(chunks)
        open_response.return_value = upstream

        async def send_request():
            client = AsyncClient()
            await client.alogin(username="chat-user", password="test-password-123")
            response = await client.post(
                "/api/chat/",
                data='{"messages":[{"role":"user","content":"Say hello"}]}',
                content_type="application/json",
                headers={"X-Chat-Owner": "browser-a"},
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
        "chat.views.open_ollama_response",
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
            HTTP_X_CHAT_OWNER="browser-a",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["ollama_status"], 404)
        open_response.assert_called_once()

    @patch("chat.views.open_ollama_response", side_effect=URLError("connection refused"))
    def test_unreachable_ollama_is_reported_as_service_unavailable(self, open_response):
        response = self.client.post(
            "/api/chat/",
            {"messages": [{"role": "user", "content": "Hello"}]},
            format="json",
            HTTP_X_CHAT_OWNER="browser-a",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], "Unable to connect to Ollama.")
        open_response.assert_called_once()


@override_settings(
    OLLAMA_DEFAULT_MODEL="test-local-model",
    CLOUD_API_KEY="server-cloud-key",
    CLOUD_API_BASE_URL="https://cloud.example/v1",
)
class CloudProviderAPITests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="cloud-user", password="test-password-123"
        )
        self.client.force_login(user)
        self.profile = AIConfiguration.get_or_create_default()
        self.profile.preferred_provider = AIConfiguration.PROVIDER_CLOUD
        self.profile.cloud_provider = "openai-compatible"
        self.profile.default_model = "cloud-chat-model"
        self.profile.save()

    def test_cloud_health_and_models_use_configured_model_without_calling_ollama(self):
        with patch("ai_gateway.views.get_ollama_models") as get_models:
            health_response = self.client.get("/api/health/")
            models_response = self.client.get("/api/models/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.data, {"status": "ok", "provider": "cloud"})
        self.assertEqual(models_response.data, {"models": [{"name": "cloud-chat-model"}]})
        get_models.assert_not_called()

    @patch("ai_gateway.providers.urlopen")
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
            HTTP_X_CHAT_OWNER="browser-a",
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
