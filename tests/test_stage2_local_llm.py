from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from engine.stage2.local_llm import (
    LocalLLMConfig,
    OllamaLocalClient,
    OpenAICompatibleLocalClient,
    build_local_llm_client,
    validate_local_base_url,
)


class Stage2LocalLLMTests(unittest.TestCase):
    def test_only_loopback_addresses_are_allowed(self):
        self.assertEqual(validate_local_base_url("http://127.0.0.1:11434"), "http://127.0.0.1:11434")
        self.assertEqual(validate_local_base_url("http://localhost:1234/"), "http://localhost:1234")
        with self.assertRaisesRegex(ValueError, "외부 또는 원격 서버"):
            validate_local_base_url("https://api.openai.com/v1")
        with self.assertRaisesRegex(ValueError, "외부 또는 원격 서버"):
            validate_local_base_url("http://192.168.0.10:11434")

    def test_ollama_client_uses_loopback_chat_endpoint_without_api_key(self):
        config = LocalLLMConfig(provider="ollama", model="local-test", base_url="http://127.0.0.1:11434")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": '{"drafts": [], "profile_summary": "test"}'}}
        with patch("engine.stage2.local_llm.requests.post", return_value=response) as post:
            client = OllamaLocalClient(config)
            result = client.generate_json(instructions="system", prompt="user")
        self.assertEqual(result["profile_summary"], "test")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:11434/api/chat")
        self.assertNotIn("headers", kwargs)

    def test_openai_compatible_client_is_local_and_has_no_authorization_header(self):
        config = LocalLLMConfig(provider="openai_compatible", model="local-test", base_url="http://127.0.0.1:1234")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"drafts": [], "profile_summary": "test"}'}}]
        }
        with patch("engine.stage2.local_llm.requests.post", return_value=response) as post:
            client = OpenAICompatibleLocalClient(config)
            result = client.generate_json(instructions="system", prompt="user")
        self.assertEqual(result["profile_summary"], "test")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertNotIn("Authorization", kwargs.get("headers", {}))

    def test_factory_rejects_remote_endpoint_fail_closed(self):
        config = LocalLLMConfig(provider="ollama", model="local-test", base_url="https://example.com")
        with self.assertRaisesRegex(ValueError, "외부 또는 원격 서버"):
            build_local_llm_client(config)


if __name__ == "__main__":
    unittest.main()
