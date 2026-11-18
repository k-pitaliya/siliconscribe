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

A model id from the browser ends up as an argument to a subprocess or a URL, so every id is checked
against MODEL_ID_RE (no leading dash, no spaces or shell characters) before it is used anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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
PROVIDER_LABELS = {"opencode": "OpenCode", "opencode-go": "OpenCode Go", "nvidia": "NVIDIA", "openrouter": "OpenRouter"}
PROVIDER_ORDER = ("opencode", "opencode-go", "nvidia", "openrouter")

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


def child_env() -> Dict[str, str]:
    """The environment handed to the `opencode` app: everything except the Cloudflare credentials, which it has no use for."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("CLOUDFLARE_")}


def is_valid_model_id(value: object) -> bool:
    return isinstance(value, str) and bool(MODEL_ID_RE.match(value))


def is_cloudflare_id(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(CLOUDFLARE_PREFIXES)


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


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ----------------------------------------------------------------------------------- OpenCode
def parse_opencode_models(text: str) -> List[dict]:
    """`provider/model` lines from `opencode models` -> model dicts, free ones first within each provider."""
    seen, models = set(), []
    for line in (text or "").splitlines():
        mid = line.strip()
        if not is_valid_model_id(mid) or "/" not in mid or mid in seen:
            continue
        seen.add(mid)
        provider, _, name = mid.partition("/")
        free = True if (name.endswith("-free") or name.endswith(":free")) else None
        models.append({
            "id": mid, "label": name, "provider": provider,
            "group": PROVIDER_LABELS.get(provider, provider),
            "free": free,
            "note": "Marked free by its name" if free else "Not marked free: may use credits or need a key for this provider",
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
