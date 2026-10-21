import argparse
import copy
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "frontend" / "test-results"
IMAGE = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "ocr"
    / "v1"
    / "images"
    / "receipt_001.jpg"
)
USER = {
    "user_id": "user-one",
    "user_name": "Кирилл",
    "user_surname": "Петров",
    "user_mail": "kirill@example.com",
}


def receipt_fixture():
    return {
        "receipt_id": "receipt-one",
        "store_name": "Продукты у дома",
        "purchase_datetime": "2026-10-21T09:45:00Z",
        "total_amount": "200.00",
        "status": "need_review",
        "created_at": "2026-10-21T10:00:00Z",
        "confirmed_at": None,
        "processing_error_message": None,
        "raw_ocr_text": "Молоко 129.90\nХлеб 70.10\nИТОГ 200.00",
        "ocr_confidence": 0.91,
        "items": [
            {
                "receipt_item_id": "milk",
                "raw_name": "МОЛОКО",
                "normalized_name": "Молоко",
                "quantity": "1",
                "unit": "шт",
                "unit_price": "129.90",
                "total_price": "129.90",
                "category_id": "food",
                "confidence": 0.72,
            },
            {
                "receipt_item_id": "bread",
                "raw_name": "ХЛЕБ",
                "normalized_name": "Хлеб",
                "quantity": "1",
                "unit": "шт",
                "unit_price": "70.10",
                "total_price": "70.10",
                "category_id": "food",
                "confidence": 0.97,
            },
        ],
    }


class Api:
    def __init__(self, signed_in=False):
        self.signed_in = signed_in
        self.receipt = receipt_fixture()
        self.user = copy.deepcopy(USER)
        self.empty = False
        self.fail_session = False
        self.fail_report = False
        self.enqueue_unconfirmed = False
        self.expired = False
        self.processing = 0
        self.calls = []
        self.reports = []
        self.period = {
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
            "timezone": "Asia/Omsk",
        }

    def handle(self, route):
        req = route.request
        parsed = urlsplit(req.url)
        path, method = parsed.path, req.method
        headers = {
            "Access-Control-Allow-Origin": req.headers.get(
                "origin", "http://localhost:5183"
            ),
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "content-type",
        }

        def reply(data=None, status=200, extra=None):
            actual = headers | (extra or {})
            route.fulfill(
                status=status,
                headers=actual,
                content_type="application/json",
                body="" if status == 204 else json.dumps(data, ensure_ascii=False),
            )

        if method == "OPTIONS":
            reply({}, 200)
            return
        body = (
            json.loads(req.post_data or "{}")
            if method in {"PATCH", "POST"} and path != "/api/receipts/upload"
            else {}
        )
        self.calls.append((method, path, body, parse_qs(parsed.query)))
        if path == "/api/auth/me":
            if self.fail_session:
                reply({"detail": "Сервис временно недоступен"}, 503)
            else:
                reply(
                    self.user if self.signed_in else {"detail": "Not authenticated"},
                    200 if self.signed_in else 401,
                )
        elif path == "/api/auth_login":
            if body["user_password"] == "wrong":
                reply({"detail": "Invalid credentials"}, 401)
            else:
                self.signed_in = True
                reply(
                    self.user,
                    extra={
                        "Set-Cookie": "session_id=frontend-test; Path=/; HttpOnly; SameSite=Lax"
                    },
                )
        elif path == "/api/register_user":
            reply(self.user, 201)
        elif path == "/api/logout":
            self.signed_in = False
            reply(status=204, extra={"Set-Cookie": "session_id=; Path=/; Max-Age=0"})
        elif self.expired:
            reply({"detail": "Session expired"}, 401)
        elif path == "/api/categories":
            reply(
                [
                    {"category_id": "food", "category_name": "Продукты"},
                    {"category_id": "other", "category_name": "Прочее"},
                ]
            )
        elif path == "/api/receipts/upload":
            assert "multipart/form-data; boundary=" in req.headers["content-type"]
            if self.enqueue_unconfirmed:
                reply(
                    {
                        "detail": {
                            "code": "receipt_enqueue_unconfirmed",
                            "message": "Чек сохранён, но очередь временно недоступна. Не загружайте фото повторно.",
                            "receipt_id": "receipt-one",
                        }
                    },
                    503,
                )
            else:
                self.processing = 1
                self.receipt["status"] = "uploaded"
                reply(self.receipt, 201)
        elif path == "/api/receipts":
            query = parse_qs(parsed.query)
            items = [] if self.empty else [self.receipt]
            if query.get("status") and self.receipt["status"] != query["status"][0]:
                items = []
            reply(
                {
                    "items": items,
                    "page": 1,
                    "page_size": 15,
                    "total": len(items),
                    "total_pages": 1 if items else 0,
                }
            )
        elif path.endswith("/image-url"):
            reply(
                {
                    "image_url": "http://localhost:9000/test/receipt.jpg",
                    "expires_in": 300,
                }
            )
        elif path == "/api/receipts/receipt-one/confirm":
            self.receipt.update(status="completed", confirmed_at="2026-10-21T10:30:00Z")
            reply(self.receipt)
        elif path == "/api/receipts/receipt-one/reprocess":
            assert body == {"replace_items": True}
            self.processing = 1
            self.receipt.update(status="uploaded", confirmed_at=None)
            reply(
                {
                    "receipt_id": "receipt-one",
                    "processing_version": 2,
                    "job_id": "test-job",
                },
                202,
            )
        elif path == "/api/receipts/receipt-one/items" and method == "POST":
            item = {
                "receipt_item_id": "new-item",
                "normalized_name": None,
                "category_id": None,
                "confidence": None,
            } | body
            self.receipt["items"].append(item)
            reply(item, 201)
        elif "/items/" in path:
            item_id = path.rsplit("/", 1)[-1]
            item = next(
                i for i in self.receipt["items"] if i["receipt_item_id"] == item_id
            )
            if method == "DELETE":
                self.receipt["items"].remove(item)
                reply(status=204)
            else:
                item.update(body)
                reply(item)
            self.receipt.update(status="need_review", confirmed_at=None)
        elif path == "/api/receipts/receipt-one":
            if method == "PATCH":
                assert isinstance(body.get("total_amount", "0"), str)
                self.receipt.update(body)
                self.receipt.update(status="need_review", confirmed_at=None)
            if self.processing:
                states = ["preprocessing", "ocr_processing", "parsing", "need_review"]
                self.receipt["status"] = states[min(self.processing - 1, 3)]
                self.processing += 1
                if self.processing > 4:
                    self.processing = 0
            reply(self.receipt)
        elif path == "/api/analytics/summary":
            reply(
                {"total_amount": "8274.60", "purchase_count": 12, "period": self.period}
            )
        elif path == "/api/analytics/categories":
            reply(
                {
                    "items": [
                        {
                            "category_id": "food",
                            "category_name": "Продукты",
                            "total_amount": "6219.70",
                            "purchase_count": 10,
                        },
                        {
                            "category_id": "cafe",
                            "category_name": "Кафе",
                            "total_amount": "2054.90",
                            "purchase_count": 2,
                        },
                    ]
                }
            )
        elif path == "/api/analytics/trends":
            reply(
                {
                    "points": [
                        {
                            "bucket_start": f"2026-10-{day:02}",
                            "total_amount": str(amount),
                            "purchase_count": 1,
                        }
                        for day, amount in [
                            (2, 650),
                            (4, 1290),
                            (7, 743),
                            (11, 2054.9),
                            (14, 358),
                            (18, 1800),
                            (21, 1378.7),
                        ]
                    ]
                }
            )
        elif path == "/api/analytics/products/top":
            reply(
                {
                    "items": [
                        {
                            "product_name": name,
                            "total_amount": amount,
                            "purchase_count": count,
                        }
                        for name, amount, count in [
                            ("Кофе зерновой", "1490.00", 2),
                            ("Молоко", "1169.10", 9),
                            ("Куриное филе", "895.30", 3),
                        ]
                    ]
                }
            )
        elif path == "/api/analytics/stores":
            reply(
                {
                    "items": [
                        {
                            "store_name": "Продукты у дома",
                            "total_amount": "6219.70",
                            "purchase_count": 10,
                        }
                    ]
                }
            )
        elif path == "/api/analytics/month-comparison":
            reply(
                {
                    "amount_change": "523.1",
                    "amount_change_percent": "6.75",
                    "current": {"total_amount": "8274.60"},
                    "previous": {"total_amount": "7751.50"},
                }
            )
        elif path == "/api/llm/reports/monthly":
            if self.fail_report:
                reply(
                    {
                        "detail": "Модель временно недоступна. Попробуйте позже.",
                        "code": "llm_unavailable",
                    },
                    503,
                )
            else:
                report = {
                    "report_id": "report-one",
                    "period_start": body["month"],
                    "period_end": "2026-10-31",
                    "created_at": "2026-10-21T10:30:00Z",
                    "model_name": "qwen3.5:4b",
                    "timezone": "Asia/Omsk",
                    "input_data": {
                        "current": {"total_amount": "8274.60", "purchase_count": 12},
                        "previous": {"total_amount": "7751.50"},
                    },
                    "report_data": {
                        "summary": "Большая часть расходов приходится на продукты. Ниже три рекомендации по покупкам.",
                        "recommendations": [
                            {
                                "title": title,
                                "reason": "Эта категория занимает заметную часть расходов.",
                                "action": action,
                            }
                            for title, action in [
                                (
                                    "Планируйте продукты",
                                    "Составьте список перед походом в магазин.",
                                ),
                                (
                                    "Сравните покупки кофе",
                                    "Сравните цену за килограмм в двух магазинах.",
                                ),
                                (
                                    "Проверьте категорию кафе",
                                    "Установите удобный месячный ориентир расходов.",
                                ),
                            ]
                        ],
                    },
                }
                self.reports.append(report)
                reply(report, 201)
        elif path == "/api/llm/reports":
            reply(
                {
                    "items": self.reports,
                    "page": 1,
                    "page_size": 10,
                    "total": len(self.reports),
                    "total_pages": 1 if self.reports else 0,
                }
            )
        elif path == "/api/llm/reports/report-one":
            reply(self.reports[0])
        elif path == "/api/llm/reports/report-late":
            reply({"detail": "Отчёт не найден."}, 404)
        else:
            raise AssertionError(f"Unexpected API call: {method} {path}")


def no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (
        "Page overflows viewport"
    )


def run(base_url):
    ARTIFACTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP localhost 127.0.0.1"]
        )
        checks = 0
        for width, theme in [(1440, "light"), (390, "light"), (320, "dark")]:
            context = browser.new_context(
                viewport={"width": width, "height": 960}, color_scheme=theme
            )
            api = Api()
            context.route(re.compile(r"^https?://[^/]+/api/"), api.handle)
            context.route(
                "**/test/receipt.jpg",
                lambda route: route.fulfill(
                    content_type="image/jpeg", body=IMAGE.read_bytes()
                ),
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e, target=errors: target.append(str(e)))
            page.goto(base_url + "/receipts/receipt-one")
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
            no_overflow(page)
            page.screenshot(
                path=str(ARTIFACTS / f"login-{width}-{theme}.png"), full_page=True
            )
            page.get_by_label("Электронная почта").fill(USER["user_mail"])
            page.get_by_label("Пароль", exact=True).fill("wrong")
            page.get_by_role("button", name="Войти", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text(
                "Неверная почта или пароль"
            )
            page.get_by_label("Пароль", exact=True).fill("valid-password-123")
            page.get_by_role("button", name="Войти", exact=True).click()
            expect(page.get_by_role("heading", name="Данные чека")).to_be_visible()
            assert any(
                c["name"] == "session_id" and c["httpOnly"] for c in context.cookies()
            )
            page.reload()
            expect(page.get_by_role("heading", name="Данные чека")).to_be_visible()
            page.wait_for_load_state("networkidle")
            no_overflow(page)
            page.screenshot(
                path=str(ARTIFACTS / f"receipt-{width}-{theme}.png"), full_page=True
            )
            page.get_by_label("Название товара МОЛОКО").fill("Молоко 3,2%")
            expect(
                page.get_by_role("button", name="Подтвердить чек", exact=True)
            ).to_be_disabled()
            page.get_by_label("Цена товара МОЛОКО").fill("140,00")
            page.get_by_role("button", name="Рассчитать сумму товара МОЛОКО").click()
            page.get_by_role("button", name="Сохранить товар МОЛОКО").click()
            expect(page.get_by_label("Название товара МОЛОКО")).to_have_value(
                "Молоко 3,2%"
            )
            page.get_by_label("Итог чека, ₽").fill("210,10")
            page.get_by_role("button", name="Сохранить", exact=True).click()
            expect(
                page.get_by_role("button", name="Подтвердить чек", exact=True)
            ).to_be_enabled()
            page.get_by_role("button", name="Подтвердить чек", exact=True).click()
            expect(
                page.get_by_role("button", name="Чек подтверждён", exact=True)
            ).to_be_visible()
            page.get_by_role("button", name="Добавить товар", exact=True).click()
            dialog = page.get_by_role("dialog")
            if width == 1440:
                page.screenshot(
                    path=str(ARTIFACTS / "add-item-dialog.png"), full_page=True
                )
            dialog.get_by_label("Название товара").fill("Тестовая позиция")
            dialog.get_by_label("Цена, ₽", exact=True).fill("0")
            dialog.get_by_label("Сумма, ₽", exact=True).fill("0")
            dialog.get_by_role("button", name="Добавить товар", exact=True).click()
            expect(
                page.get_by_label("Название товара Тестовая позиция")
            ).to_be_visible()
            page.get_by_role("button", name="Удалить товар Тестовая позиция").click()
            page.get_by_role("alertdialog").get_by_role(
                "button", name="Удалить", exact=True
            ).click()
            expect(page.get_by_label("Название товара Тестовая позиция")).to_have_count(
                0
            )
            page.get_by_role("link", name="Аналитика", exact=True).click()
            expect(
                page.get_by_role("heading", name="Динамика расходов")
            ).to_be_visible()
            page.wait_for_load_state("networkidle")
            no_overflow(page)
            page.screenshot(
                path=str(ARTIFACTS / f"analytics-{width}-{theme}.png"), full_page=True
            )
            page.get_by_label("Период", exact=True).select_option("custom")
            page.get_by_label("С", exact=True).fill("2026-10-21")
            page.get_by_label("По", exact=True).fill("2026-10-01")
            page.get_by_role("button", name="Показать", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text(
                "Начало не должно быть позже конца"
            )
            page.get_by_label("С", exact=True).fill("2026-10-01")
            page.get_by_label("По", exact=True).fill("2026-10-21")
            page.get_by_role("button", name="Показать", exact=True).click()
            page.get_by_role("link", name="Отчёты", exact=True).click()
            expect(
                page.get_by_role("heading", name="Первый отчёт ещё впереди")
            ).to_be_visible()
            api.fail_report = True
            page.get_by_role("button", name="Создать отчёт", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text(
                "Модель временно недоступна"
            )
            api.fail_report = False
            page.get_by_role("button", name="Создать отчёт", exact=True).click()
            expect(
                page.get_by_role("heading", name="На что обратить внимание")
            ).to_be_visible()
            assert page.locator(".recommendation").count() == 3
            no_overflow(page)
            page.screenshot(
                path=str(ARTIFACTS / f"report-{width}-{theme}.png"), full_page=True
            )
            page.get_by_role("link", name="К отчётам").click()
            expect(page.locator(".report-row")).to_have_count(1)
            page.get_by_role("link", name="Добавить чек", exact=True).click()
            page.locator("input[type=file]").set_input_files(
                {"name": "test.heic", "mimeType": "image/heic", "buffer": b"test"}
            )
            expect(page.get_by_role("alert")).to_contain_text("HEIC")
            page.locator("input[type=file]").set_input_files(str(IMAGE))
            expect(page.get_by_alt_text("Предпросмотр выбранного чека")).to_be_visible()
            page.wait_for_function(
                "document.querySelector('.local-preview img').naturalWidth > 0"
            )
            api.enqueue_unconfirmed = True
            page.get_by_role("button", name="Распознать чек", exact=True).click()
            expect(
                page.get_by_role("link", name="Перейти к сохранённому чеку")
            ).to_be_visible()
            expect(
                page.get_by_role("button", name="Распознать чек", exact=True)
            ).to_have_count(0)
            page.get_by_role("link", name="Чеки", exact=True).click()
            expect(page.locator(".receipt-row")).to_have_count(1)
            page.get_by_label("Статус", exact=True).select_option("failed")
            expect(page.get_by_role("heading", name="Чеки не найдены")).to_be_visible()
            page.get_by_role("button", name="Сбросить фильтры").click()
            expect(page.locator(".receipt-row")).to_have_count(1)
            page.wait_for_load_state("networkidle")
            no_overflow(page)
            page.screenshot(
                path=str(ARTIFACTS / f"receipts-{width}-{theme}.png"), full_page=True
            )
            page.get_by_role("button", name="Выйти", exact=True).click()
            expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
            api.empty = True
            api.user["user_name"] = "Другой пользователь"
            page.get_by_label("Электронная почта").fill("other@example.com")
            page.get_by_label("Пароль", exact=True).fill("valid-password-123")
            page.get_by_role("button", name="Войти", exact=True).click()
            expect(
                page.get_by_role("heading", name="Здесь будут ваши покупки")
            ).to_be_visible()
            assert page.locator(".receipt-row").count() == 0
            assert not errors, errors
            assert (
                len(
                    [
                        call
                        for call in api.calls
                        if call[1] == "/api/llm/reports/monthly"
                    ]
                )
                == 2
            )
            assert any(
                call[3].get("timezone") == ["Asia/Omsk"]
                for call in api.calls
                if call[1] == "/api/analytics/summary"
            )
            context.close()
            checks += 1
            print(f"PASS full flow {width}px {theme}", flush=True)

        context = browser.new_context(viewport={"width": 1280, "height": 900})
        api = Api()
        api.fail_session = True
        context.route(re.compile(r"^https?://[^/]+/api/"), api.handle)
        page = context.new_page()
        page.goto(base_url)
        expect(
            page.get_by_role("heading", name="Не удалось проверить сессию")
        ).to_be_visible()
        api.fail_session = False
        page.get_by_role("button", name="Повторить", exact=True).click()
        expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
        context.close()
        print("PASS session failure and retry", flush=True)

        context = browser.new_context(viewport={"width": 1440, "height": 960})
        api = Api(signed_in=True)
        context.route(re.compile(r"^https?://[^/]+/api/"), api.handle)
        context.route(
            "**/test/receipt.jpg",
            lambda route: route.fulfill(
                content_type="image/jpeg", body=IMAGE.read_bytes()
            ),
        )
        page = context.new_page()
        page.goto(base_url + "/upload")
        expect(page.get_by_role("heading", name="Фото вашего чека")).to_be_visible()
        page.locator("input[type=file]").set_input_files(str(IMAGE))
        page.get_by_role("button", name="Распознать чек", exact=True).click()
        expect(page.locator(".processing-panel")).to_be_visible()
        expect(
            page.get_by_role("button", name="Подтвердить чек", exact=True)
        ).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Распознать повторно", exact=True).click()
        expect(page.get_by_role("alertdialog")).to_be_visible()
        assert not any(call[1].endswith("/reprocess") for call in api.calls)
        page.get_by_role("alertdialog").get_by_role(
            "button", name="Отмена", exact=True
        ).click()
        page.get_by_role("button", name="Распознать повторно", exact=True).click()
        page.get_by_role("alertdialog").get_by_role(
            "button", name="Повторить распознавание"
        ).click()
        expect(page.locator(".processing-panel")).to_be_visible()
        api.expired = True
        page.get_by_role("link", name="Отчёты", exact=True).click()
        expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
        context.close()
        print(
            "PASS upload, polling, reprocess confirmation and expired session",
            flush=True,
        )
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        api = Api(signed_in=True)
        context.route(re.compile(r"^https?://[^/]+/api/"), api.handle)
        pending_reports = []
        context.route(
            "**/api/llm/reports/monthly", lambda route: pending_reports.append(route)
        )
        page = context.new_page()
        page.goto(base_url + "/reports")
        page.get_by_role("button", name="Создать отчёт", exact=True).click()
        expect(
            page.get_by_role("status")
            .filter(has_text="Модель анализирует расходы")
            .first
        ).to_be_visible()
        page.get_by_role("link", name="Чеки", exact=True).click()
        page.get_by_role("button", name="Выйти", exact=True).click()
        expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
        api.empty = True
        api.user = USER | {"user_id": "user-two", "user_name": "Другой пользователь"}
        page.get_by_label("Электронная почта").fill("other@example.com")
        page.get_by_label("Пароль", exact=True).fill("valid-password-123")
        page.get_by_role("button", name="Войти", exact=True).click()
        expect(
            page.get_by_role("heading", name="Здесь будут ваши покупки")
        ).to_be_visible()
        with page.expect_event(
            "requestfinished",
            predicate=lambda request: request.url.endswith("/api/llm/reports/monthly"),
        ):
            pending_reports[0].fulfill(
                status=201,
                content_type="application/json",
                headers={
                    "Access-Control-Allow-Origin": base_url,
                    "Access-Control-Allow-Credentials": "true",
                },
                body=json.dumps(
                    {
                        "report_id": "report-late",
                        "report_data": {"summary": "PRIVATE PREVIOUS ACCOUNT"},
                    }
                ),
            )
        page.evaluate("() => Promise.resolve()")
        expect(page).to_have_url(base_url + "/receipts")
        page.goto(base_url + "/reports/report-late")
        expect(page.get_by_role("alert")).to_contain_text("Отчёт не найден")
        expect(page.locator("body")).not_to_contain_text("PRIVATE PREVIOUS ACCOUNT")
        context.close()
        print("PASS late response isolation between accounts", flush=True)
        browser.close()
        print(f"{checks + 3} browser scenarios passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:5183")
    run(parser.parse_args().base_url)
