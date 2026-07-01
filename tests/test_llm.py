import httpx
import pytest
import respx

from imeto.core.llm import LLMClient, LLMError
from imeto.core.schemas import Extraction

URL = "http://test/v1/chat/completions"


def _completion(content: str) -> httpx.Response:
    """Minimalna atrapa odpowiedzi OpenAI Chat Completions."""
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def make_client(**kw: object) -> LLMClient:
    return LLMClient(base_url="http://test/v1", api_key="sk-none", model="test", **kw)  # type: ignore[arg-type]


def test_empty_model_rejected():
    with pytest.raises(LLMError):
        LLMClient(base_url="http://test/v1", api_key="sk-none", model="")


@respx.mock
def test_valid_json_first_try():
    respx.post(URL).mock(return_value=_completion('{"facts": []}'))
    result = make_client().structured("sys", "usr", Extraction)
    assert result.facts == []


@respx.mock
def test_strips_markdown_fences():
    fenced = '```json\n{"facts": []}\n```'
    respx.post(URL).mock(return_value=_completion(fenced))
    assert make_client().structured("sys", "usr", Extraction).facts == []


@respx.mock
def test_retries_on_invalid_then_succeeds():
    route = respx.post(URL).mock(
        side_effect=[
            _completion("to nie jest json"),
            _completion('{"facts": [{"quote": "a", "statement": "b"}]}'),
        ]
    )
    result = make_client().structured("sys", "usr", Extraction)
    assert result.facts[0].quote == "a"
    assert route.call_count == 2  # jedna korekta, potem sukces


@respx.mock
def test_exhausts_retries_raises():
    respx.post(URL).mock(return_value=_completion("nadal nie json"))
    with pytest.raises(LLMError):
        make_client(max_validation_retries=1).structured("sys", "usr", Extraction)
