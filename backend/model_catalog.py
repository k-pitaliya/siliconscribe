"""Which models can the user pick? OpenCode's own list, and Cloudflare Workers AI.

Two sources, both read live and cached so the model menu is never a stale hand-written list:

  * OpenCode: whatever `opencode models` reports for the signed-in app (about 460 ids such as
    `opencode/deepseek-v4.1-flash-free`). The CLI gives no price, so a model is marked FREE only when its
    name says so (`-free`, `:free`); every other model is "other": it may use credits or need a key, is
    hidden by default and is never claimed to be paid (that cannot be proven from here).
  * Cloudflare Workers AI: called through its OpenAI-compatible endpoint
    (https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions, Bearer token).
    The account id and token come ONLY from the environment (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN);
    the web interface never accepts or stores a secret. Model ids look like `@cf/openai/gpt-oss-120b`.

  * NVIDIA NIM (the hosted API at integrate.api.nvidia.com, OpenAI-compatible): ids are `org/model`, shown here
    with a `nim/` prefix so they can never be mistaken for OpenCode's own `nvidia/...` ids. The key comes ONLY from
    NVIDIA_NIM_API_KEY, set on purpose; no other credential in the environment is ever picked up.

A model id from the browser ends up as an argument to a subprocess or a URL, so every id is checked
against MODEL_ID_RE (no leading dash, no spaces or shell characters) before it is used anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("siliconscribe.models")

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,99}$")
CLOUDFLARE_PREFIXES = ("@cf/", "@hf/")
_ACCOUNT_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")

OPENCODE_TTL = 600.0          # seconds a successful `opencode models` listing is reused
FAILURE_TTL = 30.0            # a failed listing is retried soon
CLOUDFLARE_TTL = 1800.0
CLOUDFLARE_SEARCH_PAGES = 5   # at most 5 x 100 catalogue entries are read

DEFAULT_CLOUDFLARE_MODEL = "@cf/openai/gpt-oss-120b"
NIM_PREFIX = "nim/"
DEFAULT_NIM_BASE = "https://integrate.api.nvidia.com/v1"
DEFAULT_NIM_MODEL = "poolside/laguna-xs-2.1"
_NIM_KEY_RE = re.compile(r"^nvapi-[A-Za-z0-9_\-]{20,}$")
# Catalogue entries that are not chat models (embeddings, speech, safety classifiers, image models ...).
_NIM_NOT_CHAT = re.compile(r"embed|rerank|guard|safety|reward|parakeet|riva|canary|clip|paligemma|vision|neva|fuyu|kosmos|"
                           r"retriev|bge|diffusion|flux|whisper|tts|asr|audio|voicechat|detector|calibration|molmim|esm|"
                           r"alphafold|genmol|diffdock|cosmos|nv-", re.I)
# Listed by NVIDIA but not callable when tried (a catalogue entry that answers 404 is worse than no entry).
NIM_KNOWN_BROKEN = {"bigcode/starcoder2-15b"}      # HTTP 404 on 2026-11-18
# Answered a one-line request in seconds in a live test on 2026-11-18; listed first. Everything else follows alphabetically.
NIM_PREFERRED = ("poolside/laguna-xs-2.1", "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b",
                 "minimaxai/minimax-m3.1-flash")
PROVIDER_LABELS = {"opencode": "OpenCode", "opencode-go": "OpenCode Go", "github-copilot": "GitHub Copilot", "nvidia": "NVIDIA", "openrouter": "OpenRouter"}
PROVIDER_ORDER = ("opencode", "opencode-go", "github-copilot", "nvidia", "openrouter")
# Copilot through OpenCode: on the Free and Student plans only "auto" exists, and GitHub does not say which model it picks.
COPILOT_NOTE = ("GitHub picks the model for each request and does not say which, so a result cannot name its model "
                "and runs are not reproducible. Uses your Copilot allowance.")

# Suggested Workers AI chat models, used only when the live catalogue cannot be read.
STATIC_CLOUDFLARE = [
    ("@cf/openai/gpt-oss-120b", "OpenAI open-weight 120B reasoning model"),
    ("@cf/openai/gpt-oss-20b", "OpenAI open-weight 20B reasoning model"),
    ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "Llama 3.3 70B, fast"),
    ("@cf/qwen/qwen2.5-coder-32b-instruct", "Qwen2.5 Coder 32B, code-specialised"),
    ("@cf/deepseek-ai/deepseek-r1-distill-qwen-32b", "DeepSeek R1 distilled into Qwen 32B"),
    ("@cf/mistralai/mistral-small-3.1-24b-instruct", "Mistral Small 3.1 24B"),
    ("@cf/google/gemma-3-12b-it", "Gemma 3 12B"),
]

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, object]] = {}


# What the `opencode` app may see: system basics, locale, proxies/certificates, and its OWN settings (OPENCODE_*).
# An allowlist, not a denylist: the old denylist (CLOUDFLARE_*, NVIDIA_NIM_*) still handed NVIDIA_API_KEY, OPENAI_API_KEY,
# ZEN_API_KEY and any other exported secret to a tool-capable agent that has no use for them (self-review finding).
_CHILD_ENV_RE = re.compile(r"^(PATH|HOME|USER|LOGNAME|SHELL|TERM|TMPDIR|LANG|LC_\w+|TZ|XDG_\w+|OPENCODE_\w+|HTTPS?_PROXY|"
                           r"https?_proxy|NO_PROXY|no_proxy|ALL_PROXY|SSL_CERT_FILE|SSL_CERT_DIR|NODE_EXTRA_CA_CERTS|"
                           r"__CF_USER_TEXT_ENCODING)$")


def child_env() -> Dict[str, str]:
    """The environment handed to the `opencode` app: only the allowlisted variables above."""
    return {k: v for k, v in os.environ.items() if _CHILD_ENV_RE.match(k)}


def is_valid_model_id(value: object) -> bool:
    return isinstance(value, str) and bool(MODEL_ID_RE.match(value))


def is_cloudflare_id(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(CLOUDFLARE_PREFIXES)


def is_nim_id(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(NIM_PREFIX)


def is_claude_id(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(CLAUDE_PREFIX)


def is_routed_id(value: Optional[str]) -> bool:
    """True for ids served by a provider of their own (Cloudflare, NVIDIA NIM, Claude Code) instead of the configured one."""
    return is_cloudflare_id(value) or is_nim_id(value) or is_claude_id(value)


def normalize_opencode_id(model: str) -> str:
    """`deepseek-v4.1-flash-free` (how LLM_MODEL is usually written) -> `opencode/deepseek-v4.1-flash-free`."""
    return model if "/" in model else f"opencode/{model}"


def _get_cache(key: str, refresh: bool):
    if refresh:
        return None
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]
    return None


def _put_cache(key: str, value: object, ttl: float) -> None:
    with _lock:
        _cache[key] = (time.time() + ttl, value)


HIDDEN_FILE = Path(__file__).resolve().parent / "model_hidden.json"


def hidden_models() -> Dict[str, str]:
    """{model id: reason} for models the Model menu hides because they failed the last check (model_hidden.json).

    Read on every call (the file is tiny), so editing it takes effect on the next menu refresh. A missing or broken
    file hides nothing: a typo must never empty the menu. MODEL_HIDDEN_FILE points elsewhere (tests).
    """
    path = Path(os.getenv("MODEL_HIDDEN_FILE") or HIDDEN_FILE)
    try:
        data = json.loads(path.read_text())
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, dict):
            return {}
        return {str(k): str(v) for k, v in models.items()}
    except (OSError, ValueError):
        return {}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ----------------------------------------------------------------------------------- OpenCode
def parse_opencode_models(text: str) -> List[dict]:
    """`provider/model` lines from `opencode models` -> model dicts, free ones first within each provider."""
    seen, models = set(), []
    for line in (text or "").splitlines():
        mid = line.strip()
        if not is_valid_model_id(mid) or "/" not in mid or "://" in mid or mid in seen:   # not a stray URL line
            continue
        seen.add(mid)
        provider, _, name = mid.partition("/")
        free = True if (name.endswith("-free") or name.endswith(":free")) else None
        models.append({
            "id": mid, "label": name, "provider": provider,
            "group": PROVIDER_LABELS.get(provider, provider),
            "free": free,
            "note": COPILOT_NOTE if provider == "github-copilot" else "Marked free by its name" if free else "Not marked free: may use credits or need a key for this provider",
            "tag": "balanced", "thinking_levels": [], "reasoning": False,
        })
    rank = {p: i for i, p in enumerate(PROVIDER_ORDER)}
    models.sort(key=lambda m: (rank.get(m["provider"], len(rank)), m["provider"], 0 if m["free"] else 1, m["label"]))
    return models


def opencode_models(refresh: bool = False) -> List[dict]:
    """The models the installed OpenCode app offers (cached). Empty when the app is missing or fails."""
    hit = _get_cache("opencode", refresh)
    if hit is not None:
        return [dict(m) for m in hit]
    models: List[dict] = []
    ttl = FAILURE_TTL
    try:
        with tempfile.TemporaryDirectory(prefix="siliconscribe_ocm_") as cwd:
            p = subprocess.run(["opencode", "models"], cwd=cwd, capture_output=True, text=True, timeout=40,
                               stdin=subprocess.DEVNULL, env=child_env())
        models = parse_opencode_models(p.stdout) if p.returncode == 0 else []
        if models:
            ttl = OPENCODE_TTL
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("could not list OpenCode models: %s", type(e).__name__)
    _put_cache("opencode", models, ttl)
    return [dict(m) for m in models]


# ---------------------------------------------------------------------------------- Cloudflare
def _api_base() -> str:
    return os.getenv("CLOUDFLARE_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")


def cloudflare_config() -> Optional[Tuple[str, str]]:
    """(account id, token) from the environment, or None when either is missing or malformed."""
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = (os.getenv("CLOUDFLARE_API_TOKEN", "") or os.getenv("CLOUDFLARE_API_KEY", "")).strip()
    if not _ACCOUNT_ID_RE.match(account) or not token or token.lower().startswith("your_"):
        return None
    return account, token


def cloudflare_base_url(account_id: str) -> str:
    return f"{_api_base()}/accounts/{account_id}/ai/v1"


def _cloudflare_entry(model_id: str, note: str) -> dict:
    return {"id": model_id, "label": model_id.split("/", 2)[-1], "provider": "cloudflare", "group": "Cloudflare Workers AI",
            "free": None, "note": (note or "Cloudflare Workers AI")[:140], "tag": "balanced",
            "thinking_levels": [], "reasoning": False}


def static_cloudflare_models() -> List[dict]:
    return [_cloudflare_entry(mid, note) for mid, note in STATIC_CLOUDFLARE]


def parse_cloudflare_search(payload: dict) -> List[dict]:
    """Text-generation models out of `GET /accounts/{id}/ai/models/search`. An entry without task information is kept."""
    out = []
    for item in (payload or {}).get("result") or []:
        name = item.get("name") if isinstance(item, dict) else None
        if not is_valid_model_id(name) or not is_cloudflare_id(name):
            continue
        task = item.get("task") or {}
        task_name = str(task.get("name", "")).lower() if isinstance(task, dict) else ""
        if task_name and "text generation" not in task_name:
            continue                      # embeddings, speech, image models ... are not chat models
        out.append(_cloudflare_entry(name, str(item.get("description") or "")))
    return out


def _ssl_context() -> ssl.SSLContext:
    """Certificates the rest of the app already relies on (certifi). The python.org builds of Python ship without a
    system certificate bundle, so plain urllib cannot verify any HTTPS site there (it failed on a real machine)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _urlopen(req: urllib.request.Request, timeout: float):
    context = _ssl_context() if req.full_url.lower().startswith("https://") else None
    return urllib.request.urlopen(req, timeout=timeout, context=context)      # noqa: S310 - fixed Cloudflare endpoint, ids validated


def _search_cloudflare(account: str, token: str, timeout: float = 15.0) -> List[dict]:
    found: List[dict] = []
    for page in range(1, CLOUDFLARE_SEARCH_PAGES + 1):
        url = f"{_api_base()}/accounts/{account}/ai/models/search?" + urllib.parse.urlencode({"per_page": 100, "page": page})
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        with _urlopen(req, timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
        found += parse_cloudflare_search(payload)
        if len(payload.get("result") or []) < 100:
            break
    return found


def cloudflare_status(refresh: bool = False) -> dict:
    """{'available': bool, 'hint': str|None, 'models': [...]}. Never raises, never returns the token."""
    cfg = cloudflare_config()
    if cfg is None:
        return {"available": False, "models": [],
                "hint": "Cloudflare is not set up. Start the backend with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN set, then reload."}
    key = f"cloudflare:{cfg[0]}"
    hit = _get_cache(key, refresh)
    if hit is not None:
        return {"available": True, "models": [dict(m) for m in hit["models"]], "hint": hit["hint"]}
    models, hint = [], None
    try:
        models = _search_cloudflare(*cfg)
    except urllib.error.HTTPError as e:
        hint = f"Could not read Cloudflare's model list (HTTP {e.code}); showing suggested models. Check the token's Workers AI permission."
    except Exception as e:  # network down, bad JSON ...
        hint = f"Could not read Cloudflare's model list ({type(e).__name__}); showing suggested models."
    if not models:
        models = static_cloudflare_models()
        hint = hint or "Cloudflare returned no text models; showing suggested models."
    models.sort(key=lambda m: (m["id"] != DEFAULT_CLOUDFLARE_MODEL, m["id"]))
    _put_cache(key, {"models": models, "hint": hint}, CLOUDFLARE_TTL if not hint else FAILURE_TTL)
    return {"available": True, "models": [dict(m) for m in models], "hint": hint}


# ------------------------------------------------------------------------------------ NVIDIA NIM
def nim_config() -> Optional[Tuple[str, str]]:
    """(api key, base url) from NVIDIA_NIM_API_KEY only, or None when it is missing or not a plausible `nvapi-` key."""
    key = os.getenv("NVIDIA_NIM_API_KEY", "").strip()
    if not _NIM_KEY_RE.match(key):
        return None
    return key, os.getenv("NVIDIA_NIM_BASE_URL", DEFAULT_NIM_BASE).strip().rstrip("/")


def _nim_entry(raw_id: str, note: str = "NVIDIA NIM hosted API") -> dict:
    return {"id": NIM_PREFIX + raw_id, "label": raw_id, "provider": "nim", "group": "NVIDIA NIM",
            "free": None, "note": note, "tag": "balanced", "thinking_levels": [], "reasoning": False}


def static_nim_models() -> List[dict]:
    return [_nim_entry(m) for m in NIM_PREFERRED]


def parse_nim_models(payload: dict) -> List[dict]:
    """Chat-like models out of `GET {base}/models`, the ones verified fast first, the rest alphabetical."""
    ids = []
    for item in (payload or {}).get("data") or []:
        mid = item.get("id") if isinstance(item, dict) else None
        if is_valid_model_id(mid) and "/" in mid and not _NIM_NOT_CHAT.search(mid) and mid not in ids and mid not in NIM_KNOWN_BROKEN:
            ids.append(mid)
    ids.sort(key=lambda m: (NIM_PREFERRED.index(m) if m in NIM_PREFERRED else len(NIM_PREFERRED), m))
    return [_nim_entry(m) for m in ids]


def _search_nim(key: str, base: str, timeout: float = 20.0) -> List[dict]:
    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    with _urlopen(req, timeout) as r:
        return parse_nim_models(json.loads(r.read().decode("utf-8")))


# ----------------------------------------------------------------------------- Claude Code (the user's own CLI)
CLAUDE_PREFIX = "claude/"
# (alias passed to `claude --model`, label, note). The CLI resolves an alias to the latest model of that family.
CLAUDE_MODELS = (
    ("opus", "Claude Opus (latest)", "Claude Code on your Claude plan · strongest; uses your plan's usage"),
    ("sonnet", "Claude Sonnet (latest)", "Claude Code on your Claude plan · fast and strong; uses your plan's usage"),
    ("haiku", "Claude Haiku (latest)", "Claude Code on your Claude plan · fastest; uses your plan's usage"),
)
_CLAUDE_ALIAS_RE = re.compile(r"^[a-z][a-z0-9.\-]{0,40}$")


def claude_alias(model_id: str) -> Optional[str]:
    """`claude/opus` -> `opus`; None when the rest is not a plain model name (it becomes a CLI argument)."""
    if not is_claude_id(model_id):
        return None
    alias = model_id[len(CLAUDE_PREFIX):]
    return alias if _CLAUDE_ALIAS_RE.match(alias) else None


def claude_enabled() -> bool:
    return os.getenv("CLAUDE_CODE_PROVIDER", "1").strip().lower() not in ("0", "false", "no", "off")


def claude_status() -> dict:
    """{'available': bool, 'hint': str|None, 'models': [...]}: the Claude Code CLI on this machine, if installed."""
    if not claude_enabled():
        return {"available": False, "models": [], "hint": "Claude Code is switched off (CLAUDE_CODE_PROVIDER=0)."}
    if shutil.which("claude") is None:
        return {"available": False, "models": [],
                "hint": "Claude Code is not installed on the server (the 'claude' command was not found)."}
    models = [{"id": CLAUDE_PREFIX + a, "label": label, "provider": "claude", "group": "Claude Code", "free": None,
               "note": note, "tag": "accurate", "thinking_levels": [], "reasoning": False} for a, label, note in CLAUDE_MODELS]
    return {"available": True, "models": models, "hint": None}


def nim_status(refresh: bool = False) -> dict:
    """{'available': bool, 'hint': str|None, 'models': [...]}. Never raises, never returns the key."""
    cfg = nim_config()
    if cfg is None:
        return {"available": False, "models": [],
                "hint": "NVIDIA NIM is not set up. Start the backend with NVIDIA_NIM_API_KEY set (a key starting nvapi-), then reload."}
    cache_key = f"nim:{cfg[1]}:{cfg[0][-6:]}"
    hit = _get_cache(cache_key, refresh)
    if hit is not None:
        return {"available": True, "models": [dict(m) for m in hit["models"]], "hint": hit["hint"]}
    models, hint = [], None
    try:
        models = _search_nim(*cfg)
    except urllib.error.HTTPError as e:
        hint = f"Could not read NVIDIA's model list (HTTP {e.code}); showing the models tested fast. Check the key."
    except Exception as e:
        hint = f"Could not read NVIDIA's model list ({type(e).__name__}); showing the models tested fast."
    if not models:
        models = static_nim_models()
        hint = hint or "NVIDIA returned no chat models; showing the models tested fast."
    _put_cache(cache_key, {"models": models, "hint": hint}, CLOUDFLARE_TTL if not hint else FAILURE_TTL)
    return {"available": True, "models": [dict(m) for m in models], "hint": hint}

