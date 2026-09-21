import asyncio
import json

import httpx
import pytest

from app.llm import DeepSeek, ModelError


def test_missing_key_is_explicit_not_fake_reply():
    with pytest.raises(ModelError, match="密钥"):
        asyncio.run(DeepSeek(api_key="").complete({}))


def test_request_shape_and_json_parsing():
    def handler(request):
        body = json.loads(request.content)
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert request.headers["Authorization"] == "Bearer test-key"
        assert "json" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"reply":"你好","action":null,"evidence_ids":[]}'},
                    }
                ]
            },
        )

    result = asyncio.run(
        DeepSeek(api_key="test-key", transport=httpx.MockTransport(handler)).complete({})
    )
    assert result == {"reply": "你好", "action": None, "evidence_ids": []}


@pytest.mark.parametrize("status,attempts", [(401, 1), (402, 1), (429, 2), (503, 2)])
def test_retry_policy_does_not_retry_auth_or_balance(status, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "sensitive-provider-body"})

    with pytest.raises(ModelError) as err:
        asyncio.run(
            DeepSeek(api_key="test-key", transport=httpx.MockTransport(handler)).complete({})
        )
    assert len(calls) == attempts
    assert "sensitive-provider-body" not in str(err.value)


@pytest.mark.parametrize(
    "content,reason", [("", "stop"), ("not json", "stop"), ('{"reply":', "length")]
)
def test_empty_malformed_and_truncated_outputs_are_errors(content, reason):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, json={"choices": [{"finish_reason": reason, "message": {"content": content}}]}
        )
    )
    with pytest.raises(ModelError):
        asyncio.run(DeepSeek(api_key="test-key", transport=transport).complete({}))


def test_insecure_provider_url_rejected_before_key_can_be_sent():
    with pytest.raises(ValueError, match="HTTPS"):
        DeepSeek(api_key="test-key", base_url="http://api.deepseek.com")


def test_protocol_error_is_sanitized():
    def handler(request):
        raise httpx.RemoteProtocolError("private remote connection detail")

    with pytest.raises(ModelError, match="连接失败"):
        asyncio.run(
            DeepSeek(api_key="test-key", transport=httpx.MockTransport(handler)).complete({})
        )


@pytest.mark.parametrize("data", [{"choices": [1]}, {"choices": None}, {"choices": []}])
def test_malformed_envelope_does_not_escape_adapter(data):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    with pytest.raises(ModelError, match="JSON"):
        asyncio.run(DeepSeek(api_key="test-key", transport=transport).complete({}))


def test_retry_backoff_does_not_extend_total_request_deadline():
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    with pytest.raises(ModelError) as error:
        asyncio.run(DeepSeek(api_key="test-key", transport=transport, timeout=0.01).complete({}))
    assert error.value.code == "model_timeout"
