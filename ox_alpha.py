import sys
import os
import json
import ssl
import urllib.request
import urllib.error

def load_env(env_path=".env"):
    """Load simple key=value pairs from .env without external dependencies."""
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

load_env()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    print("❌ Error: OPENROUTER_API_KEY is not set.")
    print("👉 Please add `OPENROUTER_API_KEY=sk-or-v1-...` to your .env file.")
    sys.exit(1)

def ask_ox(prompt: str, system_prompt: str = "You are Ox Alpha, an advanced AI assistant.") -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "stealth/ox-alpha",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    # SSL context with fallback for local macOS Python certificate configurations
    try:
        context = ssl.create_default_context()
    except Exception:
        context = ssl._create_unverified_context()

    try:
        try:
            resp_handle = urllib.request.urlopen(req, context=context, timeout=60)
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                context = ssl._create_unverified_context()
                resp_handle = urllib.request.urlopen(req, context=context, timeout=60)
            else:
                raise e

        with resp_handle as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            elif "error" in data:
                return f"API Error: {data['error'].get('message', data['error'])}"
            else:
                return f"Response: {data}"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        return f"HTTP Error {e.code}: {err_msg}"
    except urllib.error.URLError as e:
        return f"Network Error: {e.reason}"
    except Exception as e:
        return f"Unexpected Error: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 ox_alpha.py \"your prompt here\"")
        sys.exit(1)

    user_prompt = " ".join(sys.argv[1:])
    print("🤖 Querying Ox Alpha (stealth/ox-alpha)...\n")
    reply = ask_ox(user_prompt)
    print(reply)
