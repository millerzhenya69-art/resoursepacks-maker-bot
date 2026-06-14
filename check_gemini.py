"""
Запусти этот скрипт локально:
  py check_gemini.py YOUR_API_KEY

Выведет список всех доступных моделей и протестирует каждую.
"""
import asyncio, aiohttp, sys, json

API_KEY = sys.argv[1] if len(sys.argv) > 1 else ""

async def main():
    if not API_KEY:
        print("Usage: py check_gemini.py YOUR_API_KEY")
        return

    # 1. Список всех моделей
    print("=== Доступные модели ===")
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
        ) as r:
            data = await r.json()
            models = data.get("models", [])
            flash_models = [
                m["name"] for m in models
                if "flash" in m["name"].lower() or "pro" in m["name"].lower()
            ]
            for m in flash_models:
                print(f"  {m}")

    print("\n=== Тест generateContent ===")
    test_payload = {
        "contents": [{"role": "user", "parts": [{"text": "Say OK"}]}],
        "generationConfig": {"maxOutputTokens": 10}
    }

    for model_full in flash_models[:8]:
        model = model_full.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=test_payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                status = r.status
                if status == 200:
                    print(f"  ✅ {model} — РАБОТАЕТ")
                elif status == 429:
                    print(f"  ⏳ {model} — QUOTA (429)")
                elif status == 404:
                    print(f"  ❌ {model} — NOT FOUND (404)")
                elif status == 403:
                    print(f"  🔑 {model} — FORBIDDEN (403) — нет доступа")
                else:
                    body = await r.text()
                    print(f"  ? {model} — HTTP {status}: {body[:80]}")

asyncio.run(main())
