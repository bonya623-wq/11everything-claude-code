"""
debug_intercept.py — перехватываем ВСЕ API запросы с CustomItem dashboard.
Покажет реальный endpoint для списка и удаления предметов.
"""
import asyncio
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
BASE    = "https://www.eldorado.gg"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page    = await context.new_page()

        api_calls = []

        async def on_response(response):
            url = response.url
            if "eldorado.gg/api" in url and response.request.method in ("GET", "DELETE", "POST"):
                try:
                    body = await response.text()
                    body_short = body[:300]
                except Exception:
                    body_short = "(не удалось прочитать)"
                api_calls.append({
                    "method": response.request.method,
                    "url":    url.replace(BASE, ""),
                    "status": response.status,
                    "body":   body_short,
                })

        page.on("response", on_response)

        print("[1] Слушаем 15 секунд.")
        print("    >>> Открой в браузере страницу где видны твои Item-лоты на Eldorado <<<")
        print("    (обычно Dashboard → My Offers → Items или Item Management)\n")

        for i in range(15, 0, -1):
            print(f"    {i}...", end="\r")
            await asyncio.sleep(1)

        print(f"\n[2] Перехвачено API вызовов: {len(api_calls)}\n")
        for c in api_calls:
            print(f"  {c['method']:6} {c['url']}")
            print(f"         статус={c['status']}  тело={c['body'][:120]}")
            print()

        await page.close()
        print("[ГОТОВО]")

asyncio.run(main())
