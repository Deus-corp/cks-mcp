#!/usr/bin/env python3
"""
CKS + LLM Client – connects local/remote LLM to cks-mcp tools.
Supports: llama_cpp (local), DeepSeek API, Groq API.
"""

from __future__ import annotations

import json, os, re, sys, time, subprocess
from typing import Any, Optional
import requests

# Загружаем переменные из .env файла (должен лежать рядом с этим скриптом)
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# LLM Wrapper (supports local & API)
# ---------------------------------------------------------------------------

try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False


class LLM:
    """Unified interface for llama_cpp, DeepSeek, and Groq."""

    def __init__(
        self,
        provider: str = "api",
        model_name: str = "deepseek-chat",
        model_path: Optional[str] = None,
        n_ctx: int = 2048,
    ):
        self.provider = provider
        self.model_name = model_name
        self.llm = None

        # API keys
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"

        if provider == "local":
            if not LLAMA_AVAILABLE:
                raise ImportError("llama-cpp-python not installed")
            path = model_path or os.path.join(os.getcwd(), "models", f"{model_name}.gguf")
            self.llm = Llama(model_path=path, n_ctx=n_ctx, verbose=False)

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 300,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        """Send a request and return a parsed JSON response (or raw text)."""
        if self.provider == "local":
            return self._generate_local(system_prompt, user_message, max_tokens, temperature, json_mode)

        # API
        if self.provider == "deepseek":
            url = self.deepseek_url
            key = self.deepseek_key
            model = self.model_name or "deepseek-chat"
        elif self.provider == "groq":
            url = self.groq_url
            key = self.groq_key
            model = self.model_name or "llama-3.3-70b-versatile"
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        if not key:
            raise RuntimeError(f"API key not set for provider '{self.provider}'. Set {self.provider.upper()}_API_KEY env var.")

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_exc = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_json(content)
            except Exception as e:
                last_exc = e
                if attempt == 2:
                    raise RuntimeError(f"API request failed after 3 attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("Unreachable")

    def _generate_local(self, system_prompt, user_message, max_tokens, temperature, json_mode):
        output = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["<|User|>", "```"],
        )
        content = output["choices"][0]["message"]["content"]
        return self._parse_json(content)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Extract JSON from LLM output."""
        text = text.strip()
        # try direct parse
        try:
            return json.loads(text)
        except:
            pass
        # try to find {...} block
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        # fallback: return raw text as error
        return {"error": "Could not parse JSON", "raw": text[:200]}


# ---------------------------------------------------------------------------
# MCP Tool Proxy
# ---------------------------------------------------------------------------

class MCPProxy:
    """Launches cks-mcp server and communicates via stdin/stdout JSON-RPC."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cks_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request = {
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        response = json.loads(self.proc.stdout.readline())
        return response.get("result", {"error": response.get("error", "unknown")})

    def close(self):
        self.proc.terminate()


# ---------------------------------------------------------------------------
# Main interactive loop
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["local", "deepseek", "groq"], default="groq")
    parser.add_argument("--model", help="Override default model for provider")
    parser.add_argument("--model-path", help="Path to local .gguf model")
    args = parser.parse_args()

    # Initialize LLM and MCP
    try:
        llm = LLM(provider=args.provider, model_name=args.model or "", model_path=args.model_path)
    except Exception as e:
        print(f"Failed to initialize LLM: {e}")
        sys.exit(1)

    mcp = MCPProxy()

    system_prompt = """
You are a knowledge assistant. You have access to these tools:
1. validate_knowledge(json_data) – validate a CKS Knowledge Structure JSON.
2. serialize_knowledge(json_data) – serialize a structure to canonical JSON.
3. explain_knowledge(json_data) – explain a structure.
4. evolve_knowledge(json_data, operations) – evolve a structure.

To call a tool, respond with a JSON object:
{"tool": "tool_name", "arguments": {"json_data": "...", "operations": [...]}}

Always include valid json_data as a string (escaped JSON).
If no tool is needed, respond with {"answer": "your answer"}.
""".strip()

    print("CKS Knowledge Assistant ready. Type 'exit' to quit.")
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except EOFError:
            break
        if user_input.lower() == "exit":
            break

        try:
            response = llm.generate(system_prompt, user_input)
        except Exception as e:
            print(f"LLM error: {e}")
            continue

        if "tool" in response:
            tool_name = response["tool"]
            arguments = response.get("arguments", {})
            print(f"[Calling tool: {tool_name}]")
            try:
                result = mcp.call(tool_name, arguments)
                print("Result:", json.dumps(result, indent=2))
            except Exception as e:
                print(f"Tool error: {e}")
        elif "answer" in response:
            print("Assistant:", response["answer"])
        else:
            print("Assistant (raw):", response)

    mcp.close()


if __name__ == "__main__":
    main()