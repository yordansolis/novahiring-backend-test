"""Cliente de IA con soporte para Anthropic y OpenAI en un solo archivo."""
import json
import time
import uuid
from decimal import Decimal, InvalidOperation

import anthropic
import openai
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import AICallRecord
from models.ops import AICallLog, PromptVersion


# ── Validadores ───────────────────────────────────────────────────────────────

class ScoreRangeValidator:
    def validate(self, response_text: str) -> bool:
        try:
            data = json.loads(response_text)
            score = Decimal(str(data.get("score", -1)))
            return Decimal("1") <= score <= Decimal("5")
        except (json.JSONDecodeError, InvalidOperation, TypeError):
            return False


class NoopValidator:
    def validate(self, response_text: str) -> bool:
        return True


# ── Backends (uno por proveedor) ──────────────────────────────────────────────

class AnthropicBackend:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, system_prompt, messages, model, max_tokens, temperature) -> tuple[str, int, int]:
        response = await self._client.messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            system=system_prompt, messages=messages,
        )
        return response.content[0].text, response.usage.input_tokens, response.usage.output_tokens


class OpenAIBackend:
    def __init__(self, api_key: str) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, system_prompt, messages, model, max_tokens, temperature) -> tuple[str, int, int]:
        openai_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await self._client.chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=temperature, messages=openai_messages,
        )
        text = response.choices[0].message.content or ""
        return text, response.usage.prompt_tokens, response.usage.completion_tokens


# ── Cliente principal ─────────────────────────────────────────────────────────

class AIClient:
    MAX_RETRIES = 2

    def __init__(self, db: AsyncSession, anthropic_api_key: str, openai_api_key: str) -> None:
        self._db = db
        self._backends = {
            "anthropic": AnthropicBackend(anthropic_api_key),
            "openai": OpenAIBackend(openai_api_key),
        }

    async def call(
        self,
        prompt_name: str,
        template_vars: dict,
        conversation_history: list[dict],
        session_id: str | None = None,
        tenant_id: str | None = None,
        request_id: str | None = None,
        validator=None,
    ) -> str:
        if validator is None:
            validator = NoopValidator()
        if request_id is None:
            request_id = str(uuid.uuid4())

        prompt = await self._get_prompt(prompt_name)
        backend = self._backends.get(prompt.provider)
        if backend is None:
            raise ValueError(f"Proveedor desconocido '{prompt.provider}' en prompt '{prompt_name}'")

        user_content = prompt.system_prompt
        for k, v in template_vars.items():
            user_content = user_content.replace(f"{{{{{k}}}}}", str(v))
        messages = conversation_history + [{"role": "user", "content": user_content}]

        for attempt in range(self.MAX_RETRIES + 1):
            start = time.monotonic()
            error: str | None = None
            text, input_tokens, output_tokens = "", 0, 0
            validation_passed = False
            try:
                text, input_tokens, output_tokens = await backend.complete(
                    system_prompt=prompt.system_prompt,
                    messages=messages,
                    model=prompt.model,
                    max_tokens=prompt.max_tokens,
                    temperature=prompt.temperature,
                )
                validation_passed = validator.validate(text)
            except Exception as exc:
                error = str(exc)
            finally:
                await self._write_audit(AICallRecord(
                    request_id=request_id, session_id=session_id,
                    prompt_version_id=prompt.id, prompt_name=prompt_name,
                    provider=prompt.provider, system_prompt=prompt.system_prompt,
                    user_messages=messages, response_text=text,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    model=prompt.model, temperature=prompt.temperature,
                    retry_count=attempt, validation_passed=validation_passed, error=error,
                ), tenant_id=tenant_id)

            if error and attempt == self.MAX_RETRIES:
                raise RuntimeError(f"Fallo después de {self.MAX_RETRIES} reintentos: {error}")
            if error:
                continue
            if validation_passed or attempt == self.MAX_RETRIES:
                return text

        raise ValueError(f"Validación fallida después de {self.MAX_RETRIES} reintentos")

    async def _get_prompt(self, name: str) -> PromptVersion:
        result = await self._db.execute(
            select(PromptVersion).where(PromptVersion.name == name, PromptVersion.is_active.is_(True))
        )
        prompt = result.scalar_one_or_none()
        if not prompt:
            raise ValueError(f"No hay prompt activo con nombre '{name}'")
        return prompt

    async def _write_audit(self, record: AICallRecord, tenant_id: str | None = None) -> None:
        log = AICallLog(
            request_id=record.request_id, session_id=record.session_id,
            tenant_id=tenant_id, prompt_version_id=record.prompt_version_id,
            prompt_name=record.prompt_name, provider=record.provider,
            model=record.model, temperature=record.temperature,
            input_tokens=record.input_tokens, output_tokens=record.output_tokens,
            latency_ms=record.latency_ms, retry_count=record.retry_count,
            validation_passed=record.validation_passed, system_prompt=record.system_prompt,
            user_messages=record.user_messages, response_text=record.response_text,
            error=record.error,
        )
        self._db.add(log)
        await self._db.commit()
