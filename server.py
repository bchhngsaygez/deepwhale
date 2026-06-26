import sys
import os

from utils import setup_utf8, load_env, get_secret_key

setup_utf8()
load_env()

import json
import time
import uuid
import threading
import io
import re
import secrets
from collections import deque
from flask import Flask, request, Response, jsonify, session, render_template, redirect, url_for, stream_with_context

from deepseek_client import (
    login, create_session, get_pow,
    call_completion, call_continue,
    delete_session, parse_sse_lines,
    collect_response, make_session, get_model_type,
)

API_KEYS = []
API_KEYS_LOCK = threading.RLock()

def load_api_keys():
    global API_KEYS
    with API_KEYS_LOCK:
        keys_json = os.environ.get("API_KEYS_JSON", "")
        if keys_json:
            try:
                parsed = json.loads(keys_json)
                if isinstance(parsed, list) and len(parsed) > 0:
                    API_KEYS = parsed
                    return
            except json.JSONDecodeError:
                pass
        legacy = os.environ.get("API_KEY", "sk-my-secret-key-1")
        if legacy:
            API_KEYS = [{"id": "default", "name": "Default", "key": legacy, "enabled": True}]
            _persist_api_keys_mem()

def _persist_api_keys_mem():
    with API_KEYS_LOCK:
        os.environ["API_KEYS_JSON"] = json.dumps(API_KEYS)
        if API_KEYS:
            os.environ["API_KEY"] = API_KEYS[0]["key"]

load_api_keys()

ACCOUNTS = []
accounts_env = os.environ.get("DEEPSEEK_ACCOUNTS", "")
if accounts_env:
    for acc_str in accounts_env.split(","):
        acc_str = acc_str.strip()
        if ":" in acc_str:
            parts = acc_str.split(":", 1)
            ACCOUNTS.append({
                "email": parts[0].strip(),
                "password": parts[1].strip(),
                "token": None
            })

if not ACCOUNTS:
    email = os.environ.get("DEEPSEEK_EMAIL", "").strip()
    password = os.environ.get("DEEPSEEK_PASSWORD", "").strip()
    if not email or not password:
        raise ValueError("ERROR: DEEPSEEK_EMAIL or DEEPSEEK_PASSWORD not configured in .env file!")
    ACCOUNTS.append({
        "email":    email,
        "password": password,
        "token":    None,
    })

AVAILABLE_MODELS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-r1",
    "deepseek-v3",
]

MODEL_ALIASES = {}

_account_lock = threading.Lock()
_current_account_index = 0

def get_active_token() -> str:
    global _current_account_index
    with _account_lock:
        if not ACCOUNTS:
            raise RuntimeError("No DeepSeek accounts configured!")

        for _ in range(len(ACCOUNTS)):
            acc = ACCOUNTS[_current_account_index]
            if not acc.get("token"):
                try:
                    print(f"[auth] Logging in account #{_current_account_index + 1}: {acc.get('email')}")
                    token = login(
                        email=acc.get("email"),
                        password=acc.get("password")
                    )
                    acc["token"] = token
                    print(f"[auth] Login OK for account #{_current_account_index + 1}: {token[:20]}...")
                except Exception as e:
                    print(f"[auth] Account #{_current_account_index + 1} ({acc.get('email')}) login failed: {e}")
                    _current_account_index = (_current_account_index + 1) % len(ACCOUNTS)
                    continue

            token = acc["token"]
            _current_account_index = (_current_account_index + 1) % len(ACCOUNTS)
            return token

        raise RuntimeError("All configured DeepSeek accounts failed to log in!")

def invalidate_token(token: str = None):
    with _account_lock:
        if token:
            for acc in ACCOUNTS:
                if acc.get("token") == token:
                    print(f"[auth] Invalidating token for account: {acc.get('email')}")
                    acc["token"] = None
                    break
        else:
            for acc in ACCOUNTS:
                acc["token"] = None

LOG_BUFFER = deque(maxlen=2000)
LOG_LOCK = threading.Lock()

class LogCapture(io.StringIO):
    def __init__(self, original):
        super().__init__()
        self._original = original
    def write(self, msg):
        if msg.strip():
            ts = time.strftime("%H:%M:%S", time.localtime())
            with LOG_LOCK:
                LOG_BUFFER.append((ts, msg.rstrip()))
        self._original.write(msg)
    def flush(self):
        self._original.flush()

_original_stdout = sys.stdout
sys.stdout = LogCapture(_original_stdout)
_original_stderr = sys.stderr
sys.stderr = LogCapture(_original_stderr)

CHAT_SESSIONS = {}
CHAT_LOCK = threading.Lock()

def get_chat_session(chat_id: str):
    with CHAT_LOCK:
        if chat_id not in CHAT_SESSIONS:
            token = get_active_token()
            sess = make_session()
            sid = create_session(token, session=sess)
            CHAT_SESSIONS[chat_id] = {
                "session_id": sid,
                "messages": [],
                "token": token,
                "http_session": sess,
                "created_at": time.time(),
            }
        return CHAT_SESSIONS[chat_id]

app = Flask(__name__)
app.secret_key = get_secret_key()
app.config['PERMANENT_SESSION_LIFETIME'] = 86400

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

def require_admin():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login_page"))
    return None

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def save_env_file(updates: dict):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    remaining = dict(updates)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                val = remaining.pop(key)
                new_lines.append(f'{key}="{val}"\n')
                continue
        new_lines.append(line)
    for key, val in remaining.items():
        new_lines.append(f'{key}="{val}"\n')
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    for key, val in updates.items():
        os.environ[key] = val

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


def get_caller_key():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        key = auth[7:].strip()
        if key:
            return key
    key = request.headers.get("X-Api-Key", "").strip()
    if key:
        return key
    return None

def require_auth():
    key = get_caller_key()
    if not key:
        return jsonify({"error": {"message": "Missing API key", "type": "invalid_request_error"}}), 401
    with API_KEYS_LOCK:
        valid = any(k["key"] == key and k.get("enabled", True) for k in API_KEYS)
    if not valid:
        return jsonify({"error": {"message": "Invalid or disabled API key", "type": "invalid_request_error"}}), 401
    return None


def build_prompt(messages: list) -> str:
    parts = []
    for msg in messages:
        role    = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            content = "\n".join(texts)
        elif not isinstance(content, str):
            content = str(content)

        if role == "system":
            parts.append(f"<system>\n{content}\n</system>")
        elif role == "user":
            parts.append(f"Human: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")

    parts.append("Assistant:")
    return "\n\n".join(parts)

def resolve_model(model: str) -> str:
    return MODEL_ALIASES.get(model.strip().lower(), model.strip())


def make_chunk(completion_id: str, model: str, delta: dict,
               finish_reason=None) -> str:
    obj = {
        "id":      completion_id,
        "object":  "chat.completion.chunk",
        "created": int(time.time()),
        "model":   model,
        "choices": [{
            "index":         0,
            "delta":         delta,
            "finish_reason": finish_reason,
        }],
    }
    return f"data: {json.dumps(obj)}\n\n"


def stream_generator(token: str, prompt: str, model: str,
                     thinking_enabled: bool, completion_id: str):
    sess = make_session()
    yield make_chunk(completion_id, model, {"role": "assistant", "content": ""})

    session_id     = None
    msg_id         = 0
    last_status    = ""

    try:
        session_id = create_session(token, session=sess)
        pow_resp   = get_pow(token, session=sess)

        lines = call_completion(
            token=token, session_id=session_id, prompt=prompt,
            model=model, thinking=thinking_enabled,
            pow_response=pow_resp, http_session=sess,
        )

        def consume(lines_gen):
            nonlocal msg_id, last_status
            for chunk in parse_sse_lines(lines_gen):
                if chunk.get("response_message_id"):
                    msg_id = int(chunk["response_message_id"])

                p = chunk.get("p", "")
                v = chunk.get("v")

                if "status" in p and isinstance(v, str):
                    last_status = v
                if "auto_continue" in p and v is True:
                    last_status = "AUTO_CONTINUE"

                if isinstance(v, str) and "content" in p:
                    yield make_chunk(completion_id, model, {"content": v})

        yield from consume(lines)

        for rnd in range(8):
            if last_status.upper() not in ("INCOMPLETE", "AUTO_CONTINUE"):
                break
            if msg_id <= 0:
                break
            print(f"[auto_continue] round {rnd+1}, msg_id={msg_id}")
            pow2 = get_pow(token, session=sess)
            cont = call_continue(token, session_id, msg_id,
                                 pow_response=pow2, http_session=sess)
            last_status = ""
            yield from consume(cont)

        yield make_chunk(completion_id, model, {}, finish_reason="stop")
        yield "data: [DONE]\n\n"

    except Exception as e:
        invalidate_token(token)
        err = {"error": {"type": "api_error", "message": str(e)}}
        yield f"data: {json.dumps(err)}\n\n"


@app.get("/healthz")
@app.get("/readyz")
def health():
    return jsonify({"status": "ok"})


@app.get("/v1/models")
@app.get("/models")
def list_models():
    err = require_auth()
    if err:
        return err
    data = [
        {"id": m, "object": "model", "created": 1700000000, "owned_by": "deepseek"}
        for m in AVAILABLE_MODELS
    ]
    return jsonify({"object": "list", "data": data})


@app.get("/v1/chat/completions")
@app.get("/chat/completions")
def chat_completions_info():
    return jsonify({
        "message": "This endpoint requires a POST request with a JSON body.",
        "usage": 'curl -X POST http://localhost:5001/v1/chat/completions -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" -d \'{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"Hello"}]}\'',
        "endpoints": {
            "/v1/chat/completions": "POST - Chat completion",
            "/v1/models": "GET - List models",
            "/healthz": "GET - Health check",
        }
    })

@app.post("/v1/chat/completions")
@app.post("/chat/completions")
def chat_completions():
    err = require_auth()
    if err:
        return err

    body = request.get_json(force=True, silent=True) or {}
    model   = resolve_model(body.get("model", "deepseek-v4-flash"))
    msgs    = body.get("messages", [])
    stream  = bool(body.get("stream", False))
    thinking_flag = body.get("thinking", None)

    if not msgs:
        return jsonify({"error": {"message": "messages required"}}), 400

    prompt = build_prompt(msgs)

    thinking_enabled = bool(thinking_flag) if thinking_flag is not None \
                       else (get_model_type(model) == "reasoner")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    try:
        token = get_active_token()
    except Exception as e:
        return jsonify({"error": {"message": f"Auth failed: {e}"}}), 500

    if stream:
        return Response(
            stream_generator(token, prompt, model, thinking_enabled, completion_id),
            mimetype="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "X-Accel-Buffering": "no",
                "Connection":       "keep-alive",
            },
        )

    sess       = make_session()
    session_id = None
    try:
        session_id = create_session(token, session=sess)
        result = collect_response(
            token=token, session_id=session_id, prompt=prompt,
            model=model, thinking=thinking_enabled, http_session=sess,
        )
    except Exception as e:
        invalidate_token(token)
        return jsonify({"error": {"message": str(e)}}), 500

    prompt_tokens     = len(prompt) // 4
    completion_tokens = len(result.get("text", "")) // 4

    resp = {
        "id":      completion_id,
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": result.get("text", "")},
            "finish_reason": result.get("finish_reason", "stop"),
        }],
        "usage": {
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      prompt_tokens + completion_tokens,
        },
    }
    if result.get("thinking"):
        resp["choices"][0]["message"]["thinking"] = result["thinking"]

    return jsonify(resp)


@app.route("/admin/login", methods=["GET"])
def admin_login_page():
    return render_template("login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True, silent=True) or {}
    pw = data.get("password", "")
    if pw == ADMIN_PASSWORD:
        session["admin_authenticated"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"error": "Invalid password"}), 401

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect(url_for("admin_login_page"))

@app.route("/admin/dashboard")
def admin_dashboard():
    err = require_admin()
    if err:
        return err
    return render_template("dashboard.html")

@app.route("/admin/api/config", methods=["GET"])
def admin_get_config():
    err = require_admin()
    if err:
        return err
    with API_KEYS_LOCK:
        safe_keys = [{"id": k["id"], "name": k["name"], "key": k["key"], "enabled": k.get("enabled", True)} for k in API_KEYS]
    return jsonify({
        "api_key":       os.environ.get("API_KEY", ""),
        "api_keys":      safe_keys,
        "port":          os.environ.get("PORT", "5001"),
        "host":          os.environ.get("HOST", "0.0.0.0"),
        "email":         os.environ.get("DEEPSEEK_EMAIL", ""),
        "password":      os.environ.get("DEEPSEEK_PASSWORD", ""),
        "accounts_raw":  os.environ.get("DEEPSEEK_ACCOUNTS", ""),
    })

@app.route("/admin/api/config", methods=["POST"])
def admin_save_config():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    updates = {}
    global ADMIN_PASSWORD
    if "admin_password" in data and data["admin_password"].strip():
        updates["ADMIN_PASSWORD"] = data["admin_password"].strip()
        ADMIN_PASSWORD = data["admin_password"].strip()
    if "api_key" in data and data["api_key"].strip():
        updates["API_KEY"] = data["api_key"].strip()
        with API_KEYS_LOCK:
            found = False
            for k in API_KEYS:
                if k["id"] == "default":
                    k["key"] = data["api_key"].strip()
                    found = True
                    break
            if not found:
                API_KEYS.insert(0, {"id": "default", "name": "Default", "key": data["api_key"].strip(), "enabled": True})
            _persist_api_keys_mem()
    if "port" in data and str(data["port"]).strip():
        updates["PORT"] = str(data["port"]).strip()
    if "host" in data and data["host"].strip():
        updates["HOST"] = data["host"].strip()
    if "email" in data and data["email"].strip():
        updates["DEEPSEEK_EMAIL"] = data["email"].strip()
    if "password" in data and data["password"].strip():
        updates["DEEPSEEK_PASSWORD"] = data["password"].strip()
    if "accounts" in data:
        val = data["accounts"].strip()
        updates["DEEPSEEK_ACCOUNTS"] = val
        ACCOUNTS.clear()
        if val:
            for acc_str in val.split(","):
                acc_str = acc_str.strip()
                if ":" in acc_str:
                    parts = acc_str.split(":", 1)
                    ACCOUNTS.append({"email": parts[0].strip(), "password": parts[1].strip(), "token": None})
    if updates:
        save_env_file(updates)
        return jsonify({"message": "Configuration saved"})
    return jsonify({"error": "No changes provided"}), 400

@app.route("/admin/api/api-keys", methods=["GET"])
def admin_get_api_keys():
    err = require_admin()
    if err:
        return err
    with API_KEYS_LOCK:
        safe = [
            {"id": k["id"], "name": k["name"], "key_preview": k["key"][:12] + "...", "enabled": k.get("enabled", True)}
            for k in API_KEYS
        ]
        return jsonify({"keys": safe})

@app.route("/admin/api/api-keys", methods=["POST"])
def admin_add_api_key():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Key name is required"}), 400
    custom_key = data.get("key", "").strip()
    with API_KEYS_LOCK:
        if any(k["name"] == name for k in API_KEYS):
            return jsonify({"error": f"Key with name '{name}' already exists"}), 400
        if custom_key:
            if any(k["key"] == custom_key for k in API_KEYS):
                return jsonify({"error": "An API key with this value already exists"}), 400
            if len(custom_key) < 6:
                return jsonify({"error": "API key must be at least 6 characters"}), 400
        new_key = custom_key or ("sk-" + secrets.token_hex(24))
        entry = {"id": secrets.token_hex(8), "name": name, "key": new_key, "enabled": True}
        API_KEYS.append(entry)
        _persist_api_keys_mem()
    save_env_file({"API_KEYS_JSON": json.dumps(API_KEYS)})
    return jsonify({"ok": True, "key": {"id": entry["id"], "name": entry["name"], "key": entry["key"], "enabled": True}})

@app.route("/admin/api/api-keys/<key_id>", methods=["PATCH"])
def admin_update_api_key(key_id):
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    with API_KEYS_LOCK:
        for k in API_KEYS:
            if k["id"] == key_id:
                if "name" in data and data["name"].strip():
                    new_name = data["name"].strip()
                    if any(kk["name"] == new_name and kk["id"] != key_id for kk in API_KEYS):
                        return jsonify({"error": f"Key with name '{new_name}' already exists"}), 400
                    k["name"] = new_name
                if "enabled" in data:
                    k["enabled"] = bool(data["enabled"])
                _persist_api_keys_mem()
                save_env_file({"API_KEYS_JSON": json.dumps(API_KEYS)})
                return jsonify({"ok": True})
        return jsonify({"error": "Key not found"}), 404

@app.route("/admin/api/api-keys/<key_id>", methods=["DELETE"])
def admin_delete_api_key(key_id):
    err = require_admin()
    if err:
        return err
    with API_KEYS_LOCK:
        for i, k in enumerate(API_KEYS):
            if k["id"] == key_id:
                API_KEYS.pop(i)
                _persist_api_keys_mem()
                save_env_file({"API_KEYS_JSON": json.dumps(API_KEYS)})
                return jsonify({"ok": True})
        return jsonify({"error": "Key not found"}), 404

@app.route("/admin/api/test", methods=["POST"])
def admin_test():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    prompt_text = data.get("prompt", "Hello!")
    use_stream = bool(data.get("stream", False))
    model = "deepseek-v4-flash"

    try:
        token = get_active_token()
    except Exception as e:
        return jsonify({"error": f"Auth failed: {e}"}), 500

    prompt = f"Human: {prompt_text}\n\nAssistant:"
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    if use_stream:
        def gen():
            yield from stream_generator(token, prompt, model, False, completion_id)
        return Response(
            gen(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    sess = make_session()
    session_id = None
    try:
        session_id = create_session(token, session=sess)
        result = collect_response(
            token=token, session_id=session_id, prompt=prompt,
            model=model, thinking=False, http_session=sess,
        )
    except Exception as e:
        invalidate_token(token)
        return jsonify({"error": str(e)}), 500

    prompt_tokens = len(prompt) // 4
    completion_tokens = len(result.get("text", "")) // 4
    return jsonify({
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.get("text", "")},
            "finish_reason": result.get("finish_reason", "stop"),
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    })


@app.route("/admin/api/accounts-status")
def admin_accounts_status():
    err = require_admin()
    if err:
        return err
    with _account_lock:
        accounts_info = []
        for acc in ACCOUNTS:
            accounts_info.append({
                "email": acc.get("email", ""),
                "has_token": acc.get("token") is not None,
                "token_prefix": (acc.get("token") or "")[:12] + "..." if acc.get("token") else None,
            })
        return jsonify({"accounts": accounts_info, "count": len(accounts_info)})


@app.route("/admin/api/chat", methods=["POST"])
def admin_chat():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    chat_id = data.get("chat_id", "default")
    message = data.get("message", "").strip()
    model = data.get("model", "deepseek-v4-flash")
    use_stream = bool(data.get("stream", False))
    thinking = bool(data.get("thinking", False))
    context_messages = data.get("context_messages")
    if context_messages is not None:
        context_messages = int(context_messages)

    if not message:
        return jsonify({"error": "Message is required"}), 400

    try:
        chat = get_chat_session(chat_id)
        chat["messages"].append({"role": "user", "content": message})
        msgs = chat["messages"]
        if context_messages is not None and context_messages >= 0:
            msgs = msgs[-context_messages:] if context_messages > 0 else [msgs[-1]]
        prompt = build_prompt(msgs)
        token = chat["token"]
        resolved = resolve_model(model)

        if use_stream:
            def gen(token=token):
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                yield make_chunk(completion_id, resolved, {"role": "assistant", "content": ""})
                session_id = chat["session_id"]
                try:
                    pow_resp = get_pow(token, session=chat["http_session"])
                    lines = call_completion(
                        token=token, session_id=session_id, prompt=prompt,
                        model=resolved, thinking=thinking,
                        pow_response=pow_resp, http_session=chat["http_session"],
                    )
                    full_text = ""
                    for chunk in parse_sse_lines(lines):
                        p = chunk.get("p", "")
                        v = chunk.get("v")
                        if isinstance(v, str) and "content" in p:
                            full_text += v
                            yield make_chunk(completion_id, resolved, {"content": v})
                    yield make_chunk(completion_id, resolved, {}, finish_reason="stop")
                    yield "data: [DONE]\n\n"
                    chat["messages"].append({"role": "assistant", "content": full_text})
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return Response(
                gen(),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
            )

        result = collect_response(
            token=token, session_id=chat["session_id"], prompt=prompt,
            model=resolved, thinking=thinking, http_session=chat["http_session"],
        )
        chat["messages"].append({"role": "assistant", "content": result.get("text", "")})
        return jsonify({
            "text": result.get("text", ""),
            "thinking": result.get("thinking", ""),
            "finish_reason": result.get("finish_reason", "stop"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/api/chat/reset", methods=["POST"])
def admin_chat_reset():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    chat_id = data.get("chat_id", "default")
    with CHAT_LOCK:
        if chat_id in CHAT_SESSIONS:
            try:
                delete_session(CHAT_SESSIONS[chat_id]["token"], CHAT_SESSIONS[chat_id]["session_id"])
            except:
                pass
            del CHAT_SESSIONS[chat_id]
    return jsonify({"ok": True})


@app.route("/admin/api/logs")
def admin_get_logs():
    err = require_admin()
    if err:
        return err
    with LOG_LOCK:
        return jsonify({"logs": list(LOG_BUFFER)})

@app.route("/admin/api/logs/stream")
def admin_log_stream():
    err = require_admin()
    if err:
        return err
    def generate():
        last_count = 0
        while True:
            with LOG_LOCK:
                current = list(LOG_BUFFER)
            if len(current) > last_count:
                new_entries = current[last_count:]
                last_count = len(current)
                for ts, msg in new_entries:
                    yield f"data: {json.dumps({'ts': ts, 'msg': msg})}\n\n"
            time.sleep(0.5)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

@app.route("/admin/api/logs/clear", methods=["POST"])
def admin_log_clear():
    err = require_admin()
    if err:
        return err
    with LOG_LOCK:
        LOG_BUFFER.clear()
    return jsonify({"ok": True})


@app.route("/admin/api/curl-test", methods=["POST"])
def admin_curl_test():
    err = require_admin()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    method = data.get("method", "GET").upper()
    path = data.get("path", "/v1/models")
    headers = data.get("headers", {})
    body = data.get("body", "")

    test_headers = {}
    api_key = os.environ.get("API_KEY", "sk-my-secret-key-1")
    for k, v in headers.items():
        test_headers[k] = v
    if "Authorization" not in test_headers and "authorization" not in {k.lower() for k in test_headers}:
        test_headers["Authorization"] = f"Bearer {api_key}"

    from urllib.parse import urlparse
    parsed = urlparse(path)
    if parsed.netloc:
        full_url = path
    else:
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "5001"))
        full_url = f"http://localhost:{port}{path}"

    import http.client
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(full_url)
        conn = http.client.HTTPConnection(parsed.netloc, timeout=30)
        conn.request(method, parsed.path + ("?" + parsed.query if parsed.query else ""),
                     body=body if body else None,
                     headers=test_headers)
        resp = conn.getresponse()
        resp_body = resp.read().decode("utf-8", errors="replace")
        if len(resp_body) > 10000:
            resp_body = resp_body[:10000] + "\n... (truncated)"
        return jsonify({
            "status": resp.status,
            "reason": resp.reason,
            "headers": dict(resp.getheaders()),
            "body": resp_body,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "message": "Endpoint not found. Here are the available endpoints:",
        "endpoints": {
            "GET /v1/models": "List available models",
            "POST /v1/chat/completions": "Chat completion (OpenAI-compatible)",
            "GET /healthz": "Health check",
            "GET /readyz": "Readiness check",
            "GET /admin/login": "Admin login page",
            "GET /admin/dashboard": "Admin dashboard",
        },
        "docs": "https://github.com/bchhngsaygez/deepwhale"
    }), 404

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5001"))
    api_key = os.environ.get("API_KEY", "sk-my-secret-key-1")

    print("=" * 50)
    print("DeepWhale (Flask) - OpenAI Compatible DeepSeek Bridge")
    print("=" * 50)
    print(f"Endpoint: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/v1/chat/completions")
    print(f"Models:   http://{host if host != '0.0.0.0' else 'localhost'}:{port}/v1/models")
    print(f"API Key:  {api_key}")
    print("=" * 50)
    print(f"Admin:    http://{host if host != '0.0.0.0' else 'localhost'}:{port}/admin/login")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin")
    print(f"Admin PW: {admin_pw}")
    print("=" * 50)
    print("[info] Starting browser and logging into DeepSeek automatically in the background...")
    threading.Thread(target=get_active_token, daemon=True).start()
    print("=" * 50)

    app.run(
        host=host,
        port=port,
        threaded=True,
        debug=False,
    )
