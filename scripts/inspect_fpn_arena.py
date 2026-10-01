"""Inspect the FPN Arena schedule network traffic with Playwright.

Run on macOS with:
    uv run python inspect_fpn_arena.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

import httpx
from playwright.sync_api import (
    Browser,
    BrowserType,
    Request,
    Response,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError

DEFAULT_URL = "https://po01_25-26.arenadisplay.live/home/schedule"
NETWORK_TYPES = {"xhr", "fetch"}
BODY_SAMPLE_LENGTH = 2_000


@dataclass
class JsonResponse:
    """JSON response and the request that produced it."""

    request: Request
    response: Response
    body: Any
    content_type: str


def body_sample(value: Any, limit: int = BODY_SAMPLE_LENGTH) -> str:
    """Return a readable, bounded JSON sample."""
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}\n... [truncated]"


def launch_browser(chromium: BrowserType, headed: bool) -> Browser:
    """Prefer the locally installed Chrome and fall back to Playwright Chromium."""
    try:
        return chromium.launch(channel="chrome", headless=not headed)
    except PlaywrightError:
        try:
            return chromium.launch(headless=not headed)
        except PlaywrightError as exc:
            raise RuntimeError(
                "No compatible browser was found. Run: uv run playwright install chromium"
            ) from exc


def candidate_score(item: JsonResponse) -> int:
    """Rank JSON responses likely to contain schedule or match data."""
    url = item.response.url.lower()
    serialized = json.dumps(item.body, ensure_ascii=False, default=str).lower()
    score = 0

    if "/assets/" in url:
        score -= 100
    if "/api/game/getfiltered" in url:
        score += 50
    elif "/api/game/" in url:
        score += 20
    elif "/api/competition/getbydomain" in url:
        score += 10

    for keyword, weight in {
        "schedule": 10,
        "calendar": 8,
        "fixture": 8,
        "match": 7,
        "game": 5,
        "event": 4,
        "api": 2,
    }.items():
        if keyword in url:
            score += weight
        if keyword in serialized[:20_000]:
            score += weight

    entity = item.body.get("entity") if isinstance(item.body, dict) else item.body
    if isinstance(entity, list):
        score += 2
        if entity and isinstance(entity[0], dict) and "gameDate" in entity[0]:
            score += 25
    elif isinstance(item.body, dict):
        for key in ("data", "items", "results", "matches", "games", "events"):
            if key in item.body:
                score += 3

    return score


def safe_request_headers(request: Request) -> dict[str, str]:
    """Keep only headers useful for replaying an API request."""
    allowed = {
        "accept",
        "authorization",
        "content-type",
        "origin",
        "referer",
        "user-agent",
        "x-api-key",
        "x-requested-with",
    }
    return {
        name: value
        for name, value in request.all_headers().items()
        if name.lower() in allowed
    }


def direct_request(
    candidate: JsonResponse,
    browser_cookies: list[dict[str, Any]],
) -> None:
    """Try the candidate endpoint with httpx, first anonymously, then as replay."""
    request = candidate.request
    method = request.method
    content = request.post_data.encode() if request.post_data is not None else None
    content_type = request.header_value("content-type")
    minimal_headers = {"content-type": content_type} if content_type else {}

    print("\n=== DIRECT HTTPX TEST ===")
    print(f"Candidate: {method} {request.url}")

    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in browser_cookies
        if "name" in cookie and "value" in cookie
    }
    replay_headers = safe_request_headers(request)

    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            minimal = client.request(
                method,
                request.url,
                headers=minimal_headers,
                content=content,
            )
            print(f"Anonymous/minimal status: {minimal.status_code}")
            print(
                "Anonymous/minimal content-type: "
                f"{minimal.headers.get('content-type', '')}"
            )

            if "json" in minimal.headers.get("content-type", "").lower():
                print("Anonymous/minimal JSON sample:")
                print(body_sample(minimal.json()))
            else:
                print(f"Anonymous/minimal body sample: {minimal.text[:500]}")

            client.cookies.update(cookies)
            replay = client.request(
                method,
                request.url,
                headers=replay_headers,
                content=content,
            )
    except httpx.HTTPError as exc:
        print(f"httpx request failed: {exc}")
        return

    print(f"Browser-session replay status: {replay.status_code}")
    print(f"Replay content-type: {replay.headers.get('content-type', '')}")
    print(f"Replay header names: {sorted(replay_headers)}")
    print(f"Replay cookie names: {sorted(cookies)}")
    if "json" in replay.headers.get("content-type", "").lower():
        print("Replay JSON sample:")
        print(body_sample(replay.json()))


def inspect(url: str, headed: bool, wait_ms: int, test_httpx: bool) -> None:
    """Open the page and inspect its XHR/fetch responses."""
    json_responses: list[JsonResponse] = []
    failed_requests: list[Request] = []

    with sync_playwright() as playwright:
        browser = launch_browser(playwright.chromium, headed)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response: Response) -> None:
            request = response.request
            if request.resource_type not in NETWORK_TYPES:
                return

            content_type = response.headers.get("content-type", "")
            print("\n=== XHR/FETCH RESPONSE ===")
            print(f"method: {request.method}")
            print(f"status: {response.status}")
            print(f"url: {response.url}")
            print(f"content-type: {content_type}")

            if "json" not in content_type.lower():
                return

            try:
                body = response.json()
            except PlaywrightError as exc:
                print(f"JSON body unavailable: {exc}")
                return

            print("JSON sample:")
            print(body_sample(body))
            json_responses.append(JsonResponse(request, response, body, content_type))

        def on_request_failed(request: Request) -> None:
            if request.resource_type in NETWORK_TYPES:
                failed_requests.append(request)

        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

        print(f"Opening: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightError:
            print("Network did not become idle; continuing with captured traffic.")
        page.wait_for_timeout(wait_ms)

        if failed_requests:
            print("\n=== FAILED XHR/FETCH REQUESTS ===")
            for request in failed_requests:
                print(f"{request.method} {request.url}: {request.failure}")

        if not json_responses:
            print("\nNo JSON XHR/fetch responses were captured.")
            browser.close()
            return

        ranked = sorted(json_responses, key=candidate_score, reverse=True)
        candidate = ranked[0]
        print("\n=== LIKELY SCHEDULE ENDPOINT ===")
        print(f"score: {candidate_score(candidate)}")
        print(f"method: {candidate.request.method}")
        print(f"url: {candidate.response.url}")
        print(f"content-type: {candidate.content_type}")
        if candidate.request.post_data:
            print(f"request body: {candidate.request.post_data}")
        if isinstance(candidate.body, dict):
            print(f"root keys: {sorted(candidate.body)}")
            entity = candidate.body.get("entity")
            if isinstance(entity, list):
                print(f"entity count: {len(entity)}")
                if entity and isinstance(entity[0], dict):
                    print(f"first entity keys: {sorted(entity[0])}")

        if test_httpx:
            direct_request(candidate, context.cookies())

        browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=5_000,
        help="Extra wait after page load (default: 5000)",
    )
    parser.add_argument(
        "--no-httpx",
        action="store_true",
        help="Do not replay the likely endpoint with httpx",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    inspect(
        url=arguments.url,
        headed=arguments.headed,
        wait_ms=arguments.wait_ms,
        test_httpx=not arguments.no_httpx,
    )
