"""
debug_list_items.py — смотрим реальные ID CustomItem лотов на Eldorado
и сравниваем с тем что сохранено в lot_pairs.json.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
BASE    = "https://www.eldorado.gg"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page    = await context.new_page()

        captured = {}
        def on_req(req):
            h = req.headers
            if "x-xsrf-token" in h or "X-XSRF-Token" in h:
                captured.update(h)
        page.on("request", on_req)

        print("[1] Открываем CustomItem dashboard...")
        await page.goto(
            f"{BASE}/dashboard/offers?category=CustomItem&pageIndex=1&pageSize=40",
            wait_until="domcontentloaded", timeout=20000
        )
        await asyncio.sleep(3)

        xsrf = captured.get("x-xsrf-token") or captured.get("X-XSRF-Token") or ""
        print(f"[2] XSRF len={len(xsrf)}")

        # Пробуем разные endpoints для получения списка CustomItem лотов
        endpoints = [
            "/api/v1/item-management/me/offers?pageIndex=0&pageSize=20",
            "/api/v1/item-management/me/offers/item?pageIndex=0&pageSize=20",
            "/api/flexibleOffers/me/search?pageIndex=1&pageSize=20&category=CustomItem",
        ]

        for ep in endpoints:
            print(f"\n[3] GET {ep}")
            result = await page.evaluate("""
                async ({url, xsrf}) => {
                    try {
                        const r = await fetch(url, {
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json',
                                'X-XSRF-Token': xsrf,
                            }
                        });
                        let body = '';
                        try { body = await r.text(); } catch(e) {}
                        return {status: r.status, body: body.slice(0, 1500)};
                    } catch(e) {
                        return {status: -1, error: String(e)};
                    }
                }
            """, {"url": ep, "xsrf": xsrf})
            print(f"    Статус: {result.get('status')}")
            print(f"    Тело:   {result.get('body') or result.get('error')}")

        # Показываем что сейчас в lot_pairs.json
        print("\n[4] Текущие ID в lot_pairs.json (items секция):")
        pairs_file = Path("lot_pairs.json")
        if pairs_file.exists():
            data = json.loads(pairs_file.read_text(encoding="utf-8"))
            for p in data.get("items", []):
                print(f"    ELD: {p['eldorado_lot_id']}  FP: {p['funpay_lot_id']}")
        else:
            print("    lot_pairs.json не найден")

        await page.close()
        print("\n[ГОТОВО]")

asyncio.run(main())
