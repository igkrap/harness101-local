import unittest
import json
import os
import urllib.request
from unittest.mock import patch, MagicMock
from harness.harness import LocalLLMClient, HarnessError

class TestLocalLLMClientOptions(unittest.TestCase):
    def setUp(self):
        self.client = LocalLLMClient(url="http://localhost:8080", model="gemma-4")
        # Clear relevant env vars to start clean
        for key in ["LOCAL_LLM_THINKING", "LOCAL_LLM_MAX_TOKENS"]:
            if key in os.environ:
                del os.environ[key]

    @patch("model_transport.complete")
    def test_default_config(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices": []}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        self.client.chat([{"role": "user", "content": "hi"}])
        
        # Check payload defaults
        call_args = mock_urlopen.call_args[0][0]
        payload = json.loads(call_args.data.decode('utf-8'))
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertEqual(payload["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(payload["temperature"], 1.0)

    @patch("model_transport.complete")
    def test_thinking_and_max_tokens_config(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices": []}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        os.environ["LOCAL_LLM_THINKING"] = "true"
        os.environ["LOCAL_LLM_MAX_TOKENS"] = "8192"

        self.client.chat([{"role": "user", "content": "hi"}])

        call_args = mock_urlopen.call_args[0][0]
        payload = json.loads(call_args.data.decode('utf-8'))
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertEqual(payload["chat_template_kwargs"]["enable_thinking"], True)

    @patch("model_transport.complete")
    def test_invalid_max_tokens_fallback(self, mock_urlopen):
        os.environ["LOCAL_LLM_MAX_TOKENS"] = "99999"  # Invalid

        with self.assertRaises(HarnessError):
            self.client.chat([{"role": "user", "content": "hi"}])

        mock_urlopen.assert_not_called()

    def test_budget_violation(self):
        # Large message that exceeds budget (32768 limit)
        # 32768 / 3 approx 10922 chars. 
        # If we use max_tokens 8192, we have (32768-8192)*3 = 75228 chars allowed.
        # Wait, the budget calculation is (chars/3) + max_tokens.
        # If chars = 80000, tokens = 26666 + 8192 = 34858 > 32768.
        large_msg = [{"role": "user", "content": "a" * 80000}]
        os.environ["LOCAL_LLM_MAX_TOKENS"] = "8192"
        
        with self.assertRaises(HarnessError) as cm:
            self.client.chat(large_msg)
        self.assertIn("Token budget exceeded", str(cm.exception))

    @patch("model_transport.complete")
    def test_strips_reasoning_fields(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices": []}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "reasoning": "thinking..."}
        ]

        self.client.chat(messages)
        call_args = mock_urlopen.call_args[0][0]
        payload = json.loads(call_args.data.decode('utf-8'))
        
        # Check that reasoning is gone from the outgoing payload
        for m in payload["messages"]:
            self.assertNotIn("reasoning", m)
            self.assertNotIn("reasoning_content", m)

if __name__ == "__main__":
    unittest.main()
