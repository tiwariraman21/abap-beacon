"""AI providers.

All providers implement `complete(prompt) -> AIResponse`. Selection (`get_provider()`): the ATLAS_AI_PROVIDER environment variable, else
the saved configuration in data/config/ai.json (edited on the "AI provider"
page), else auto-detect (Claude Code if installed, then Ollama if running).

  claude-code   Claude Code CLI in headless mode - uses a Claude subscription
  anthropic     Anthropic API (ANTHROPIC_API_KEY)
  ollama        local open-source models (llama3.1, qwen2.5-coder, mistral...) -
                free, nothing leaves the machine; http://localhost:11434
  lmstudio      local models via LM Studio's OpenAI-compatible server
  groq          free tier, very fast Llama/Mixtral hosting (api.groq.com)
  openrouter    free models (":free" suffix) and paid ones behind one key
  gemini        Google Gemini via its OpenAI-compatible endpoint (free tier)
  mistral       Mistral API (free tier)
  openai        OpenAI
  custom        any OpenAI-compatible /v1/chat/completions endpoint
  manual        prompt-pack files you paste into any chat UI yourself

All hosted providers share one implementation (OpenAICompatibleProvider). The
same guardrails apply to every provider: text is redacted before it leaves.

Claude Code specifics: the prompt is sent on stdin (Windows command lines are
limited to ~32k characters), the CLI runs in an empty working directory so no
project CLAUDE.md or tools interfere, and `--output-format json` gives us the
result text plus usage/cost. Usage-limit responses are surfaced as
`status="limit"` so the caller can pause and resume later.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class AIError(Exception):
    pass


class AILimitReached(AIError):
    """The subscription / rate limit is exhausted; try again later."""


@dataclass
class AIResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)


class ClaudeCodeProvider:
    name = "claude-code"

    def __init__(self, command: str | None = None, model: str | None = None, extra_args: list[str] | None = None, timeout: int = 600):
        self.command = command or os.environ.get("ATLAS_CLAUDE_CMD", "claude")
        self.model = model or os.environ.get("ATLAS_CLAUDE_MODEL", "")
        env_args = os.environ.get("ATLAS_CLAUDE_ARGS", "")
        self.extra_args = extra_args if extra_args is not None else (env_args.split() if env_args else [])
        self.timeout = timeout

    @classmethod
    def available(cls) -> bool:
        return shutil.which(os.environ.get("ATLAS_CLAUDE_CMD", "claude")) is not None

    def complete(self, prompt: str, instruction: str = "Follow the instructions in the input exactly and reply with the requested output only.") -> AIResponse:
        exe = shutil.which(self.command)
        if exe is None:
            raise AIError(f"'{self.command}' not found on PATH. Install Claude Code or set ATLAS_CLAUDE_CMD.")
        args = [exe, "-p", instruction, "--output-format", "json", *self.extra_args]
        if self.model:
            args += ["--model", self.model]
        with tempfile.TemporaryDirectory(prefix="atlas-ai-") as workdir:
            try:
                proc = subprocess.run(args, input=prompt, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=self.timeout, cwd=workdir, shell=False)
            except subprocess.TimeoutExpired:
                raise AIError(f"Claude Code did not answer within {self.timeout}s.")
        stdout, stderr = proc.stdout.strip(), proc.stderr.strip()
        payload = _parse_json_output(stdout)
        text = payload.get("result") if isinstance(payload, dict) else None
        if proc.returncode != 0 or (isinstance(payload, dict) and payload.get("is_error")):
            message = (text or stderr or stdout)[:500]
            if re.search(r"limit|quota|too many requests|429|exhausted", message, re.I):
                raise AILimitReached(message)
            raise AIError(f"Claude Code exited with {proc.returncode}: {message}")
        if text is None:
            text = stdout
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        return AIResponse(
            text=text,
            model=str(payload.get("model", self.model)) if isinstance(payload, dict) else self.model,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            cost_usd=float(payload.get("total_cost_usd", 0.0) or 0.0) if isinstance(payload, dict) else 0.0,
            raw=payload if isinstance(payload, dict) else {},
        )


# --------------------------------------------------------------------- OpenAI-compatible family

@dataclass
class Preset:
    name: str
    label: str
    base_url: str
    default_model: str
    key_env: str = ""
    needs_key: bool = True
    local: bool = False
    max_input_chars: int = 24000
    key_url: str = ""
    note: str = ""


PRESETS: dict[str, Preset] = {
    "ollama": Preset("ollama", "Ollama (local, free, offline)", "http://localhost:11434/v1", "llama3.1", "", False, True, 16000, "https://ollama.com/download",
                     "Install Ollama, then `ollama pull llama3.1` (or qwen2.5-coder:7b for code). Nothing leaves your machine."),
    "lmstudio": Preset("lmstudio", "LM Studio (local, free, offline)", "http://localhost:1234/v1", "local-model", "", False, True, 16000, "https://lmstudio.ai",
                       "Start the local server in LM Studio and load a model."),
    "groq": Preset("groq", "Groq (free tier)", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY", True, False, 20000, "https://console.groq.com/keys",
                   "Free tier with per-minute token limits; ABAP Beacon pauses and resumes on 429."),
    "openrouter": Preset("openrouter", "OpenRouter (free models)", "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", "OPENROUTER_API_KEY", True, False, 24000, "https://openrouter.ai/keys",
                         "Models ending in :free cost nothing; switch models without changing code."),
    "gemini": Preset("gemini", "Google Gemini (free tier)", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash", "GEMINI_API_KEY", True, False, 60000, "https://aistudio.google.com/apikey",
                     "Large context, generous free tier."),
    "mistral": Preset("mistral", "Mistral (free tier)", "https://api.mistral.ai/v1", "mistral-small-latest", "MISTRAL_API_KEY", True, False, 24000, "https://console.mistral.ai/api-keys", ""),
    "openai": Preset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY", True, False, 60000, "https://platform.openai.com/api-keys", ""),
    "custom": Preset("custom", "Custom OpenAI-compatible endpoint", "", "", "ATLAS_AI_API_KEY", False, False, 24000, "", "Any server exposing /v1/chat/completions (vLLM, Azure OpenAI proxy, company gateway)."),
}


class OpenAICompatibleProvider:
    """Chat-completions client (urllib only) for Ollama, LM Studio, Groq, OpenRouter, Gemini,
    Mistral, OpenAI and any compatible gateway."""

    def __init__(self, preset: str, base_url: str = "", api_key: str = "", model: str = "", max_input_chars: int | None = None, timeout: int = 300):
        p = PRESETS.get(preset, PRESETS["custom"])
        self.preset = p
        self.name = preset
        self.base_url = (base_url or p.base_url).rstrip("/")
        self.api_key = api_key or (os.environ.get(p.key_env, "") if p.key_env else "")
        self.model = model or p.default_model
        self.max_input_chars = max_input_chars or p.max_input_chars
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "no base URL configured"
        if self.preset.needs_key and not self.api_key:
            return False, f"no API key (set {self.preset.key_env} or enter it on the AI provider page)"
        if self.preset.local:
            try:
                import urllib.request

                urllib.request.urlopen(urllib.request.Request(self.base_url + "/models"), timeout=3).read()
            except Exception as error:
                return False, f"{self.preset.label} not reachable at {self.base_url} ({type(error).__name__})"
        return True, "ready"

    def complete(self, prompt: str, instruction: str = "") -> AIResponse:
        import urllib.error
        import urllib.request

        messages = []
        if instruction:
            messages.append({"role": "system", "content": instruction})
        messages.append({"role": "user", "content": prompt})
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "stream": False}
        if self.name in ("ollama",):
            body["options"] = {"num_ctx": 16384}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        if self.name == "openrouter":
            req.add_header("HTTP-Referer", "https://github.com/infrabeat/abap-beacon")
            req.add_header("X-Title", "ABAP Beacon custom-code intelligence")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            if error.code in (429, 402) or re.search(r"rate limit|quota|exceeded|insufficient", detail, re.I):
                raise AILimitReached(f"{self.preset.label}: HTTP {error.code} {detail}")
            raise AIError(f"{self.preset.label}: HTTP {error.code} {detail}")
        except urllib.error.URLError as error:
            raise AIError(f"{self.preset.label} not reachable at {self.base_url}: {error.reason}")
        except TimeoutError:
            raise AIError(f"{self.preset.label} timed out after {self.timeout}s")
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise AIError(f"{self.preset.label}: unexpected response {str(data)[:300]}")
        usage = data.get("usage", {}) or {}
        return AIResponse(text=text, model=str(data.get("model", self.model)), input_tokens=int(usage.get("prompt_tokens", 0) or 0), output_tokens=int(usage.get("completion_tokens", 0) or 0), cost_usd=0.0, raw={})


# --------------------------------------------------------------------- configuration

def config_path(output_dir: Path | None = None) -> Path:
    from atlas.config import get_settings

    return get_settings().data_dir / "config" / "ai.json"


def load_config() -> dict:
    path = config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ATLAS_ANTHROPIC_MODEL", "claude-sonnet-4-5")

    @classmethod
    def available(cls) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, prompt: str, instruction: str = "") -> AIResponse:
        import anthropic

        client = anthropic.Anthropic()
        message = client.messages.create(model=self.model, max_tokens=8000, system=instruction or anthropic.NOT_GIVEN, messages=[{"role": "user", "content": prompt}])
        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        return AIResponse(text=text, model=message.model, input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens)


class ManualProvider:
    """Writes the prompt to a file and stops; the user pastes it into Claude and
    imports the reply with `atlas ai-import`."""

    name = "manual"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    @classmethod
    def available(cls) -> bool:
        return True

    def complete(self, prompt: str, instruction: str = "") -> AIResponse:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        n = len(list(self.output_dir.glob("prompt_*.txt"))) + 1
        path = self.output_dir / f"prompt_{n:03d}.txt"
        path.write_text((instruction + "\n\n" if instruction else "") + prompt, encoding="utf-8")
        raise AIError(f"Manual mode: prompt written to {path}. Paste it into Claude, save the JSON reply as {path.with_suffix('.json').name} and run `atlas ai-import`.")


def _parse_json_output(stdout: str) -> dict | None:
    if not stdout:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # stream-json or noise: take the last JSON object in the output
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return None
    if isinstance(data, list):   # array of messages -> last result message
        for item in reversed(data):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        return None
    return data if isinstance(data, dict) else None


def _auto_name() -> str:
    if ClaudeCodeProvider.available():
        return "claude-code"
    if AnthropicProvider.available():
        return "anthropic"
    if OpenAICompatibleProvider("ollama").available()[0]:
        return "ollama"
    for preset in ("groq", "openrouter", "gemini", "mistral", "openai"):
        if os.environ.get(PRESETS[preset].key_env):
            return preset
    return "manual"


class AIDisabled(AIError):
    """Raised when the active workspace runs in strict mode (AI switched off)."""


class DisabledProvider:
    name = "disabled"

    @classmethod
    def available(cls) -> bool:
        return False

    def complete(self, prompt: str, instruction: str = "") -> "AIResponse":
        raise AIDisabled("AI is switched off for this workspace (strict mode). Every analysis, number and document still works without it.")


def ai_allowed() -> bool:
    """False when the active workspace is in strict mode - no provider is ever constructed then."""
    try:
        from atlas.workspace import current_slug, load_info

        return not load_info(current_slug()).strict
    except Exception:      # noqa: BLE001
        return True


def get_provider(name: str | None = None, output_dir: Path | None = None):
    if not ai_allowed():
        return DisabledProvider()
    cfg = load_config()
    name = (name or os.environ.get("ATLAS_AI_PROVIDER", "") or cfg.get("provider", "") or "auto").lower()
    if name == "auto":
        name = _auto_name()
    if name in ("claude-code", "claude", "cc"):
        return ClaudeCodeProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "manual":
        return ManualProvider(output_dir or Path("data/output/prompts"))
    if name in PRESETS:
        use_cfg = cfg if cfg.get("provider") == name else {}
        return OpenAICompatibleProvider(
            name,
            base_url=os.environ.get("ATLAS_AI_BASE_URL", "") or use_cfg.get("base_url", ""),
            api_key=os.environ.get("ATLAS_AI_API_KEY", "") or use_cfg.get("api_key", ""),
            model=os.environ.get("ATLAS_AI_MODEL", "") or use_cfg.get("model", ""),
            max_input_chars=use_cfg.get("max_input_chars") or None,
        )
    raise AIError(f"Unknown AI provider {name!r}. Choose one of: claude-code, anthropic, {', '.join(PRESETS)}, manual")


def provider_ready(provider) -> tuple[bool, str]:
    if isinstance(provider, DisabledProvider):
        return (False, "AI is switched off for this workspace (strict mode)")
    if isinstance(provider, ClaudeCodeProvider):
        return (True, "ready") if ClaudeCodeProvider.available() else (False, "`claude` command not found - install Claude Code and log in, or choose another provider")
    if isinstance(provider, AnthropicProvider):
        return (True, "ready") if AnthropicProvider.available() else (False, "ANTHROPIC_API_KEY not set")
    if isinstance(provider, OpenAICompatibleProvider):
        return provider.available()
    if isinstance(provider, ManualProvider):
        return True, "manual mode: prompts are written to files for you to paste"
    return False, "unknown"


def provider_status() -> dict:
    try:
        provider = get_provider()
        ready, reason = provider_ready(provider)
        model = getattr(provider, "model", "")
        name = provider.name
    except AIError as error:
        provider, ready, reason, model, name = None, False, str(error), "", "?"
    return {
        "selected": name, "model": model, "ready": ready and name != "manual", "reason": reason,
        "claude-code": ClaudeCodeProvider.available(),
        "anthropic": AnthropicProvider.available(),
        "ollama": OpenAICompatibleProvider("ollama").available()[0],
        "configured": load_config().get("provider", ""),
        "options": [{"id": k, "label": v.label, "local": v.local, "needs_key": v.needs_key, "default_model": v.default_model, "key_url": v.key_url, "note": v.note, "base_url": v.base_url} for k, v in PRESETS.items()],
    }


def test_provider(name: str, base_url: str = "", api_key: str = "", model: str = "") -> dict:
    """Send a one-line prompt and report the outcome (used by the AI provider page)."""
    try:
        if name in PRESETS:
            provider = OpenAICompatibleProvider(name, base_url, api_key, model)
        else:
            provider = get_provider(name)
        ready, reason = provider_ready(provider)
        if not ready:
            return {"ok": False, "message": reason}
        response = provider.complete("Reply with exactly: OK", "You are a connectivity test. Reply with the single word OK.")
        return {"ok": True, "message": f"{provider.name} / {response.model or getattr(provider, 'model', '')} answered: {response.text.strip()[:60]}"}
    except AIError as error:
        return {"ok": False, "message": str(error)[:300]}
