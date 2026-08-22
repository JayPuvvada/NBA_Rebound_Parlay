import os
import sys
import json
import ssl
import urllib.request
import urllib.error
import time

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

def collect_codebase():
    included_extensions = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json", ".sh", ".md", ".txt"
    }
    exclude_dirs = {
        ".git", "node_modules", "__pycache__", ".claude", "dist", "build", ".venv", "venv", ".idea", ".vscode"
    }
    exclude_files = {
        ".env", ".env.local", ".env.production", "package-lock.json",
        "nba_cache.json", "injury_report.json", ".DS_Store", "server.log",
        "ox_alpha_codebase_review.md"
    }

    code_files = {}
    
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
        for file in sorted(files):
            if file in exclude_files or file.startswith("."):
                continue
            ext = os.path.splitext(file)[1]
            if ext in included_extensions or file in {"Procfile"}:
                rel_path = os.path.relpath(os.path.join(root, file), ".")
                try:
                    with open(rel_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        code_files[rel_path] = content
                except Exception as e:
                    print(f"⚠️ Warning: Could not read {rel_path}: {e}")
                    
    return code_files

def review_codebase():
    print("📦 Gathering codebase files (excluding .env, data caches, build artifacts)...")
    files = collect_codebase()
    total_chars = sum(len(c) for c in files.values())
    print(f"✅ Gathered {len(files)} files (~{total_chars:,} characters, ~{total_chars // 4:,} tokens).")

    system_prompt = (
        "You are Ox Alpha, an elite Senior Software Architect, ML Engineer, and Full-Stack Code Reviewer. "
        "Your task is to conduct a thorough, highly insightful, structured, and actionable code review of the provided "
        "entire NBA Parlay Rebound Prediction application.\n\n"
        "Provide your review in organized sections:\n"
        "1. 🌟 Executive Summary & Architectural Overview\n"
        "2. 🛡️ Critical Issues, Potential Bugs & Reliability Risks (e.g. data fetching, edge cases, error handling)\n"
        "3. 🧠 ML & Statistical Modeling Insights (feature engineering, leakage prevention, calibration, parlay EV calculations)\n"
        "4. ⚡ Backend & API Improvements (Flask endpoints, caching strategy, concurrency, rate limiting for NBA API)\n"
        "5. 🎨 Frontend UI/UX & React/TypeScript Optimization (state management, component boundaries, re-renders, UX polish)\n"
        "6. 🧪 Testing & Code Quality Recommendations (unit/integration test coverage, typing, folder structure)\n"
        "7. 🚀 Concrete Priority Action Plan (Top 5 highest-ROI improvements to make next)\n\n"
        "Be specific: reference exact file names, functions, and logic where applicable, and give concrete code snippets / patterns for suggested fixes."
    )

    code_payload = []
    code_payload.append("# CODEBASE STRUCTURE & FILE CONTENTS\n")
    for file_path, content in sorted(files.items()):
        code_payload.append(f"## File: `{file_path}`\n```\n{content}\n```\n")

    user_message = (
        "Here is the complete codebase for my NBA Rebound Parlay Model application. "
        "Please review the entire codebase thoroughly and provide comprehensive, actionable recommendations to improve performance, accuracy, code architecture, reliability, and UX.\n\n"
        + "\n".join(code_payload)
    )

    print("🚀 Sending codebase to Ox Alpha via OpenRouter API (this may take 30-90 seconds)...")
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "stealth/ox-alpha",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        context = ssl.create_default_context()
    except Exception:
        context = ssl._create_unverified_context()

    try:
        try:
            resp_handle = urllib.request.urlopen(req, context=context, timeout=300)
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                context = ssl._create_unverified_context()
                resp_handle = urllib.request.urlopen(req, context=context, timeout=300)
            else:
                raise e

        with resp_handle as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "choices" in data and len(data["choices"]) > 0:
                review_content = data["choices"][0]["message"]["content"]
                
                output_file = "ox_alpha_codebase_review.md"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(review_content)
                
                print(f"\n🎉 Code review complete! Saved full review to `{output_file}`.\n")
                print("=" * 80)
                print(review_content)
                print("=" * 80)
                return review_content
            elif "error" in data:
                print(f"❌ API Error: {data['error'].get('message', data['error'])}")
            else:
                print(f"Response: {data}")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        print(f"❌ HTTP Error {e.code}: {err_msg}")
    except urllib.error.URLError as e:
        print(f"❌ Network Error: {e.reason}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")

if __name__ == "__main__":
    review_codebase()
