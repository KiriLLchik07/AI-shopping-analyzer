import json
import re
import subprocess
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://localhost:5184"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "ai-shopping-frontend-smoke",
    "-f",
    "docker-compose.yaml",
    "-f",
    "frontend/tests/compose.smoke.yaml",
]


def verify_target():
    command = COMPOSE + [
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "from backend.app.core.config import setting; from sqlalchemy.engine import make_url; print(make_url(setting.database_url).database)",
    ]
    actual = subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    )
    assert actual.stdout.strip() == "ai_shopping_test", (
        "Refusing to create a user outside the smoke database"
    )
    mapping = subprocess.run(
        COMPOSE + ["port", "frontend", "8080"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert mapping.stdout.strip() == "127.0.0.1:5184", "Unexpected frontend port"


def check_routes():
    opener = build_opener(ProxyHandler({}))
    with opener.open(BASE_URL + "/healthz", timeout=5) as response:
        assert response.status == 200 and response.read().strip() == b"ok"
    with opener.open(BASE_URL + "/health/ready", timeout=10) as response:
        assert json.load(response)["status"] == "ok"
    with opener.open(BASE_URL + "/receipts/deep-link", timeout=5) as response:
        assert b'id="root"' in response.read()
    with opener.open(BASE_URL + "/index.html", timeout=5) as response:
        assert response.headers["Cache-Control"] == "no-store"
    for path in ["/api/no-such-endpoint", "/assets/no-such-file.js"]:
        try:
            opener.open(BASE_URL + path, timeout=5)
        except HTTPError as error:
            assert error.code == 404
            if path.startswith("/api/"):
                assert "application/json" in error.headers["Content-Type"]
        else:
            raise AssertionError(f"Expected a real 404 for {path}")


def run():
    verify_target()
    check_routes()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP localhost 127.0.0.1"]
        )
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()
        errors = []
        api_responses = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                api_responses.append((response.url, response.status))
                if "/api/" in response.url
                else None
            ),
        )
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
        page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        page.get_by_label("Имя", exact=True).fill("Тест")
        page.get_by_label("Фамилия", exact=True).fill("Docker")
        email = f"smoke-{uuid4().hex}@example.com"
        page.get_by_label("Электронная почта").fill(email)
        page.get_by_label(re.compile(r"^Пароль")).fill("docker-smoke-password-12345")
        started = perf_counter()
        page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        expect(
            page.get_by_role("heading", name="Здесь будут ваши покупки")
        ).to_be_visible(timeout=20_000)
        print(
            "Real registration and login seconds:",
            round(perf_counter() - started, 3),
            flush=True,
        )
        assert any(
            cookie["name"] == "session_id" and cookie["httpOnly"]
            for cookie in context.cookies()
        )
        page.reload()
        expect(
            page.get_by_role("heading", name="Здесь будут ваши покупки")
        ).to_be_visible()
        started = perf_counter()
        page.get_by_role("link", name="Аналитика", exact=True).click()
        expect(
            page.get_by_role("heading", name="За этот период пока нет покупок")
        ).to_be_visible(timeout=10_000)
        page.wait_for_load_state("networkidle")
        print(
            "Real initial analytics seconds:",
            round(perf_counter() - started, 3),
            flush=True,
        )
        analytics = [
            (url, status) for url, status in api_responses if "/api/analytics/" in url
        ]
        assert len(analytics) >= 6 and all(status == 200 for _, status in analytics)
        assert all(url.startswith(BASE_URL + "/api/") for url, _ in api_responses)
        page.get_by_role("button", name="Выйти", exact=True).click()
        expect(page.get_by_role("heading", name="С возвращением")).to_be_visible()
        page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        page.get_by_label("Имя", exact=True).fill("Тест")
        page.get_by_label("Фамилия", exact=True).fill("Docker")
        page.get_by_label("Электронная почта").fill(email)
        page.get_by_label(re.compile(r"^Пароль")).fill("docker-smoke-password-12345")
        started = perf_counter()
        with page.expect_response(
            lambda response: "/api/register_user" in response.url
        ) as duplicate:
            page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        assert duplicate.value.status == 409
        print(
            "Real duplicate registration seconds:",
            round(perf_counter() - started, 3),
            flush=True,
        )
        expect(page.get_by_role("alert")).to_be_visible()
        assert not errors, errors
        browser.close()
    print(
        "Docker smoke passed: SPA, proxy, cookies, registration, session and analytics",
        flush=True,
    )


if __name__ == "__main__":
    run()
