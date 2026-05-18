"""
debug_delete.py — диагностика удаления CustomItem лота с Eldorado.
Запуск: python debug_delete.py
"""
import asyncio
import json
from playwright.async_api import async_playwright

CDP_URL  = "http://127.0.0.1:9222"
BASE     = "https://www.eldorado.gg"

LOT_ID = input("Введи eldorado_lot_id из lot_pairs.json: ").strip()

ENDPOINTS = [
    f"/api/v1/item-management/me/offers/item/{LOT_ID}",
    f"/api/flexibleOffersUser/me/{LOT_ID}",
]

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

        print("\n[1] Открываем dashboard чтобы перехватить токены...")
        await page.goto(
            f"{BASE}/dashboard/offers?category=CustomItem&pageIndex=1&pageSize=40",
            wait_until="domcontentloaded", timeout=20000
        )
        await asyncio.sleep(3)

        xsrf = captured.get("x-xsrf-token") or captured.get("X-XSRF-Token") or ""
        print(f"[2] XSRF token len={len(xsrf)}: {xsrf[:40]}...")

        for endpoint in ENDPOINTS:
            print(f"\n[3] Пробуем DELETE {endpoint}")
            result = await page.evaluate("""
                async ({url, xsrf}) => {
                    try {
                        const r = await fetch(url, {
                            method: 'DELETE',
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json, text/plain, */*',
                                'Content-Type': 'application/json',
                                'X-XSRF-Token': xsrf,
                            }
                        });
                        let body = '';
                        try { body = await r.text(); } catch(e) {}
                        return {status: r.status, body: body.slice(0, 300)};
                    } catch(e) {
                        return {status: -1, error: String(e)};
                    }
                }
            """, {"url": endpoint, "xsrf": xsrf})
            print(f"    Статус: {result.get('status')}")
            print(f"    Тело:   {result.get('body') or result.get('error')}")

        await page.close()
        print("\n[ГОТОВО]")

asyncio.run(main())
