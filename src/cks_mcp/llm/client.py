"""
Provider-routing LLM client for tools that need *tool calling*
(currently just ``ai_chat`` -- see cks-mcp ADR-011 §6).

``construct_knowledge`` already has a provider router
(``CKS_LLM_PROVIDER=auto|ollama|anthropic|openai_compatible``) for its single-shot
text-in/text-out extraction calls; this module applies the same
routing convention to the tool-calling case, where the LLM must be
able to request tool invocations and get their results back in a
follow-up turn.

``LLMClient.call_with_tools`` always returns the Anthropic content-block
envelope (``{'content': [block, ...]}``) regardless of which provider
actually answered, so callers (``ai_chat``'s loop) don't need any
provider-specific branching.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from cks_mcp import llm_providers

# Signature shared by both providers' tool-calling entry points:
# keyword-only messages/tools/tool_name in, {'content': [...]} out.
_ProviderFn = Callable[..., dict[str, Any]]

# Signature shared by the single-shot (no tools) text-in/text-out entry
# points: call_ollama / call_anthropic / call_openai_compatible_single_shot
# all take (prompt, *, system_prompt, model, max_tokens, tool_name=None)
# and return a plain str.
_SingleShotFn = Callable[..., str]


class LLMProviderUnavailable(RuntimeError):
    """Raised when no LLM provider could be used at all.

    Distinct from a plain ``RuntimeError`` (a single provider call
    that failed, e.g. a bad Ollama response or an Anthropic HTTP
    error) so callers can tell "nothing is configured/reachable"
    apart from "the configured provider errored", and report each
    with its own error code instead of just crashing.
    """


class LLMClient:
    """Routes a tool-calling chat turn to Ollama or Anthropic.

    The provider functions are injected (rather than imported and
    called directly) so tests -- and callers like ``ai_chat`` that
    already import ``call_anthropic_with_tools`` by name for their own
    mocking convention -- can substitute fakes without needing to
    patch this module.
    """

    def __init__(
        self,
        *,
        anthropic_fn: _ProviderFn = llm_providers.call_anthropic_with_tools,
        ollama_fn: _ProviderFn = llm_providers.call_ollama_with_tools,
        openai_compatible_fn: _ProviderFn = llm_providers.call_openai_compatible_with_tools,
        ollama_available_fn: Callable[[], bool] = llm_providers.ollama_available,
        single_shot_ollama_fn: _SingleShotFn = llm_providers.call_ollama,
        single_shot_anthropic_fn: _SingleShotFn = llm_providers.call_anthropic,
        single_shot_openai_compatible_fn: _SingleShotFn = (
            llm_providers.call_openai_compatible_single_shot
        ),
    ) -> None:
        self._anthropic_fn = anthropic_fn
        self._ollama_fn = ollama_fn
        self._openai_compatible_fn = openai_compatible_fn
        self._ollama_available_fn = ollama_available_fn
        self._single_shot_ollama_fn = single_shot_ollama_fn
        self._single_shot_anthropic_fn = single_shot_anthropic_fn
        self._single_shot_openai_compatible_fn = single_shot_openai_compatible_fn

    def call_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """Route to whichever provider ``CKS_LLM_PROVIDER`` selects.

        Returns ``{'content': [block, ...]}``, the same shape
        ``call_anthropic_with_tools`` already returns. Raises
        ``LLMProviderUnavailable`` if (and only if) no provider could
        be used at all -- e.g. 'auto' with neither Ollama reachable
        nor ``ANTHROPIC_API_KEY`` set. Any other failure (explicit
        provider errored, unknown provider value) is raised as a plain
        ``RuntimeError``, same convention every provider primitive in
        ``llm_providers`` already follows.
        """
        provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

        if provider == "ollama":
            return self._call_ollama(messages, tools, tool_name)

        if provider == "anthropic":
            return self._call_anthropic(messages, tools, tool_name)

        if provider == "openai_compatible":
            return self._call_openai_compatible(messages, tools, tool_name)

        if provider != "auto":
            raise RuntimeError(
                f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', "
                "'anthropic', or 'openai_compatible'."
            )

        # auto: prefer a local, keyless model if one is already
        # running; otherwise fall through to Anthropic. Mirrors
        # construct_knowledge's _call_llm dispatch exactly.
        # 'openai_compatible' is never picked automatically -- its
        # base URL/model/key vary too much across providers to guess
        # safely, so it must be selected explicitly via
        # CKS_LLM_PROVIDER=openai_compatible.
        if self._ollama_available_fn():
            return self._call_ollama(messages, tools, tool_name)

        try:
            return self._call_anthropic(messages, tools, tool_name)
        except RuntimeError as exc:
            if "ANTHROPIC_API_KEY" not in str(exc):
                raise
            model_hint = os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
            raise LLMProviderUnavailable(
                "No LLM provider available for ai_chat. Options: "
                "(1) run a local model -- `ollama serve` + "
                f"`ollama pull {model_hint}` -- no API key needed, "
                "this tool auto-detects it on localhost:11434 (set "
                "CKS_LLM_PROVIDER=ollama to force it); "
                "(2) set ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic."
            ) from exc

    def _call_ollama(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str | None,
    ) -> dict[str, Any]:
        model = os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return self._ollama_fn(messages=messages, tools=tools, model=model, tool_name=tool_name)

    def _call_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str | None,
    ) -> dict[str, Any]:
        model = os.environ.get("CKS_ANTHROPIC_MODEL")
        kwargs: dict[str, Any] = {"messages": messages, "tools": tools, "tool_name": tool_name}
        if model:
            kwargs["model"] = model
        return self._anthropic_fn(**kwargs)

    def _call_openai_compatible(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str | None,
    ) -> dict[str, Any]:
        model = os.environ.get("CKS_OPENAI_MODEL")
        kwargs: dict[str, Any] = {"messages": messages, "tools": tools, "tool_name": tool_name}
        if model:
            kwargs["model"] = model
        return self._openai_compatible_fn(**kwargs)

    # -----------------------------------------------------------------
    # Single-shot (no tools) text-in/text-out -- for tools like
    # construct_knowledge that just need a plain completion, not a
    # tool-calling loop.
    # -----------------------------------------------------------------

    def call_single_shot(
        self,
        prompt: str,
        *,
        system_prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        tool_name: str | None = None,
    ) -> tuple[str, str]:
        """Route a single-shot (no tools) completion to whichever
        provider ``CKS_LLM_PROVIDER`` selects.

        Returns ``(text, model_used)``. Raises ``LLMProviderUnavailable``
        if (and only if) no provider could be used at all -- e.g. 'auto'
        with neither Ollama reachable nor ``ANTHROPIC_API_KEY`` set,
        mirroring ``call_with_tools``'s contract. Any other failure
        (explicit provider errored, unknown provider value) is raised as
        a plain ``RuntimeError``.

        Like ``call_with_tools``, 'auto' never picks 'openai_compatible'
        automatically -- it must be selected explicitly via
        ``CKS_LLM_PROVIDER=openai_compatible``, since its base
        URL/model/key combination can't be guessed safely.
        """
        provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

        if provider == "ollama":
            return self._single_shot_ollama(prompt, system_prompt, model, max_tokens, tool_name)

        if provider == "anthropic":
            return self._single_shot_anthropic(prompt, system_prompt, model, max_tokens, tool_name)

        if provider == "openai_compatible":
            return self._single_shot_openai_compatible(
                prompt, system_prompt, model, max_tokens, tool_name
            )

        if provider != "auto":
            raise RuntimeError(
                f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', "
                "'anthropic', or 'openai_compatible'."
            )

        # auto: prefer a local, keyless model if one is already
        # running; otherwise fall through to Anthropic.
        if self._ollama_available_fn():
            return self._single_shot_ollama(prompt, system_prompt, model, max_tokens, tool_name)

        try:
            return self._single_shot_anthropic(prompt, system_prompt, model, max_tokens, tool_name)
        except RuntimeError as exc:
            if "ANTHROPIC_API_KEY" not in str(exc):
                raise
            raise LLMProviderUnavailable(
                "No single-shot LLM provider available. Options: "
                "(1) run a local model -- `ollama serve` -- no API key needed, "
                "this auto-detects it on localhost:11434 (set "
                "CKS_LLM_PROVIDER=ollama to force it); "
                "(2) set ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; "
                "(3) set CKS_OPENAI_API_KEY and CKS_LLM_PROVIDER=openai_compatible."
            ) from exc

    def _single_shot_ollama(
        self,
        prompt: str,
        system_prompt: str,
        model: str | None,
        max_tokens: int,
        tool_name: str | None,
    ) -> tuple[str, str]:
        resolved_model = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        text = self._single_shot_ollama_fn(
            prompt,
            system_prompt=system_prompt,
            model=resolved_model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )
        return text, resolved_model

    def _single_shot_anthropic(
        self,
        prompt: str,
        system_prompt: str,
        model: str | None,
        max_tokens: int,
        tool_name: str | None,
    ) -> tuple[str, str]:
        resolved_model = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
        text = self._single_shot_anthropic_fn(
            prompt,
            system_prompt=system_prompt,
            model=resolved_model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )
        return text, resolved_model

    def _single_shot_openai_compatible(
        self,
        prompt: str,
        system_prompt: str,
        model: str | None,
        max_tokens: int,
        tool_name: str | None,
    ) -> tuple[str, str]:
        resolved_model = model or os.environ.get("CKS_OPENAI_MODEL", "gpt-4o")
        text = self._single_shot_openai_compatible_fn(
            prompt,
            system_prompt=system_prompt,
            model=resolved_model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )
        return text, resolved_model
