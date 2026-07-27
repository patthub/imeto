"""Model-agnostic LLM client (§8). The only touch point with a model: OpenAI Chat
Completions. Swapping models = change base_url/model, zero code changes.

Two kinds of retry are kept separate:
- network (429/5xx/timeout) — handled by the openai SDK itself (`max_retries`),
  not duplicated here,
- validation — a parse→validate(Pydantic)→(append error)→retry loop (§6.1). This
  is the anti-hallucination safety net: until the model returns JSON matching the
  schema, the result is not accepted."""

import re
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """Model failed to return a valid, schema-conforming result within the retry
    limit."""


def _strip_fences(text: str) -> str:
    # ponytail: small models wrap JSON in ```...``` — strip the code block if present.
    #           No deeper cleanup: that's what the validation loop is for.
    m = _FENCE.search(text)
    return m.group(1) if m else text


def _correction(err: ValidationError) -> str:
    return (
        "The previous response did not satisfy the required JSON schema. "
        "Validation errors:\n"
        f"{err}\n"
        "Return only valid JSON conforming to the schema — no comment, no ```."
    )


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        json_mode: bool = False,
        max_validation_retries: int = 2,
        network_retries: int = 2,
        timeout: float = 120.0,
    ) -> None:
        if not model:
            raise LLMError("llm_model is not set (provide an id from /v1/models)")
        self.model = model
        self.temperature = temperature
        self.json_mode = json_mode
        self.max_validation_retries = max_validation_retries
        # network_retries: SDK retries 429/5xx/timeout — we don't back off ourselves.
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=network_retries,
            timeout=timeout,
        )

    def _call(self, messages: list[dict[str, str]]) -> str:
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
        return resp.choices[0].message.content or ""

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Call the model and return a result validated against `schema`.
        On mismatch, append the error message and retry, up to the retry limit."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_err: ValidationError | None = None
        for _ in range(self.max_validation_retries + 1):
            content = self._call(messages)
            try:
                return schema.model_validate_json(_strip_fences(content))
            except ValidationError as err:
                last_err = err
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": _correction(err)})
        raise LLMError(
            f"model did not return a valid {schema.__name__} in "
            f"{self.max_validation_retries + 1} attempts"
        ) from last_err
