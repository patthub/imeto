"""Klient LLM, model-agnostyczny (§8). Jedyny punkt styku z modelem: OpenAI Chat
Completions. Wymienność modelu = zmiana base_url/model, zero zmian w kodzie.

Dwa rodzaje ponawiania są rozdzielone:
- sieciowe (429/5xx/timeout) — robi SAM SDK openai (`max_retries`), nie dublujemy,
- walidacyjne — pętla parse→validate(Pydantic)→(dolep błąd)→retry (§6.1). To jest
  siatka bezpieczeństwa anty-halucynacji: dopóki model nie zwróci JSON zgodnego ze
  schematem, wynik nie jest przyjmowany."""

import re
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """Model nie zwrócił poprawnego, zgodnego ze schematem wyniku w limicie prób."""


def _strip_fences(text: str) -> str:
    # ponytail: małe modele owijają JSON w ```...``` — zdejmujemy blok kodu, jeśli jest.
    #           Głębszego czyszczenia nie robimy: od tego jest pętla walidacji.
    m = _FENCE.search(text)
    return m.group(1) if m else text


def _correction(err: ValidationError) -> str:
    return (
        "Poprzednia odpowiedź nie spełniła wymaganego schematu JSON. Błędy walidacji:\n"
        f"{err}\n"
        "Zwróć wyłącznie poprawny JSON zgodny ze schematem — bez komentarza, bez ```."
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
            raise LLMError("llm_model nie jest ustawiony (podaj id z /v1/models)")
        self.model = model
        self.temperature = temperature
        self.json_mode = json_mode
        self.max_validation_retries = max_validation_retries
        # network_retries: SDK ponawia 429/5xx/timeout — nie robimy backoffu sami.
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
        """Wywołuje model i zwraca wynik zwalidowany względem `schema`.
        Przy niezgodności dokleja komunikat błędu i ponawia, do limitu prób."""
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
            f"model nie zwrócił poprawnego {schema.__name__} w "
            f"{self.max_validation_retries + 1} próbach"
        ) from last_err
