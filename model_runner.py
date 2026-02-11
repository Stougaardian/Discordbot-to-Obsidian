import json
import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import List, Dict

import requests

from config import settings


class ModelRunner(ABC):
    @abstractmethod
    def run(self, system_prompt: str, conversation: List[Dict[str, str]], vault_snippets: List[Dict[str, str]]) -> str:
        raise NotImplementedError


class LocalCodexRunner(ModelRunner):
    def __init__(self) -> None:
        self.codex_bin = settings.codex_bin
        self.codex_args = shlex.split(settings.codex_args) if settings.codex_args else []
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def run(self, system_prompt: str, conversation: List[Dict[str, str]], vault_snippets: List[Dict[str, str]]) -> str:
        prompt = _format_prompt(system_prompt, conversation, vault_snippets)
        cmd = [self.codex_bin, "exec"] + self.codex_args

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=self.repo_root,
                timeout=settings.request_timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return "Local codex binary not found. Check CODEX_BIN."
        except subprocess.TimeoutExpired:
            return "Local codex exec timed out."

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return f"Local codex exec failed: {error}"

        return result.stdout.strip()


class OpenAIRunner(ModelRunner):
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIRunner")

    def run(self, system_prompt: str, conversation: List[Dict[str, str]], vault_snippets: List[Dict[str, str]]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation)
        if vault_snippets:
            snippets_text = _format_snippets(vault_snippets)
            messages.append({"role": "system", "content": f"Vault snippets:\n{snippets_text}"})

        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": messages,
            "temperature": 0.2,
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=settings.request_timeout_s,
        )
        if response.status_code != 200:
            return f"OpenAI API error: {response.status_code} {response.text}"

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def _format_snippets(vault_snippets: List[Dict[str, str]]) -> str:
    formatted = []
    for idx, snippet in enumerate(vault_snippets, start=1):
        formatted.append(
            "\n".join(
                [
                    f"[{idx}] {snippet['path']}#{snippet['heading']} (lines {snippet['line_start']}-{snippet['line_end']})",
                    snippet["excerpt"],
                ]
            )
        )
    return "\n\n".join(formatted)


def _format_prompt(system_prompt: str, conversation: List[Dict[str, str]], vault_snippets: List[Dict[str, str]]) -> str:
    lines = ["SYSTEM:", system_prompt.strip(), "", "CONVERSATION:"]
    for message in conversation:
        role = message.get("role", "user")
        content = message.get("content", "")
        role_label = "User" if role == "user" else "Assistant"
        lines.append(f"{role_label}: {content}")
    if vault_snippets:
        lines.append("")
        lines.append("VAULT SNIPPETS:")
        lines.append(_format_snippets(vault_snippets))
    lines.append("")
    lines.append("ASSISTANT:")
    return "\n".join(lines)


def get_runner() -> ModelRunner:
    if settings.model_backend == "openai":
        return OpenAIRunner()
    return LocalCodexRunner()
