"""Offline unit tests for the browser runtime policy and lifecycle."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from browser_agt.browser import (
    BrowserJob,
    BrowserPolicyError,
    BrowserRuntime,
    ObservedElement,
    _screenshot_shifted,
)


def _png_frame(*, changed_area: bool = False, tiny_change: bool = False) -> bytes:
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    if changed_area:
        draw.rectangle((0, 120, 1279, 500), fill="navy")
    elif tiny_change:
        draw.rectangle((10, 10, 11, 11), fill="red")
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def test_screenshot_shift_signal_ignores_tiny_changes_and_detects_page_movement() -> None:
    initial = _png_frame()

    assert _screenshot_shifted(None, initial) is None
    assert _screenshot_shifted(initial, initial) is False
    assert _screenshot_shifted(initial, _png_frame(tiny_change=True)) is False
    assert _screenshot_shifted(initial, _png_frame(changed_area=True)) is True


class FakeRoute:
    """Minimal intercepted request used by the offline safety tests."""

    def __init__(self, method: str, url: str) -> None:
        self.request = type("Request", (), {"method": method, "url": url})()
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


class FakeContext:
    """Context double that records closure without launching a browser."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeLocator:
    """Record whether a browser interaction reached the page double."""

    def __init__(self) -> None:
        self.clicked = False
        self.filled = False

    async def click(self, **kwargs: object) -> None:
        self.clicked = True

    async def fill(self, value: str, **kwargs: object) -> None:
        self.filled = True


class FakePage:
    """Page double for interaction-policy checks."""

    def __init__(self) -> None:
        self.target = FakeLocator()
        self.viewport_size = {"width": 1280, "height": 720}
        self.mouse = type("Mouse", (), {})()
        self.keyboard = type("Keyboard", (), {})()

    def locator(self, selector: str) -> FakeLocator:
        return self.target


@pytest.mark.asyncio
async def test_blocks_non_read_requests() -> None:
    """Mutation requests are aborted before reaching the destination."""
    runtime = BrowserRuntime(allow_local=True)
    context = FakeContext()
    job = BrowserJob(runtime, context)
    route = FakeRoute("POST", "https://example.com/form")

    await job._guard_request(route)

    assert route.aborted
    assert not route.continued


@pytest.mark.asyncio
async def test_allows_read_request_in_explicit_local_mode() -> None:
    """Explicit local mode supports isolated UI fixtures and permits safe reads."""
    runtime = BrowserRuntime(allow_local=True)
    job = BrowserJob(runtime, FakeContext())
    route = FakeRoute("GET", "http://127.0.0.1:8000/")

    await job._guard_request(route)

    assert route.continued


@pytest.mark.asyncio
async def test_rejects_local_navigation_by_default() -> None:
    """The public runtime refuses local destinations before navigating."""
    runtime = BrowserRuntime()

    with pytest.raises(BrowserPolicyError, match="local destinations"):
        await runtime._validate_url("http://localhost:8000")


@pytest.mark.asyncio
async def test_rejects_non_http_url() -> None:
    """Only credential-free HTTP(S) destinations are accepted."""
    runtime = BrowserRuntime(allow_local=True)

    with pytest.raises(BrowserPolicyError, match=r"HTTP\(S\)"):
        await runtime._validate_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_job_close_is_idempotent() -> None:
    """Closing a job twice safely closes its context once."""
    context = FakeContext()
    job = BrowserJob(BrowserRuntime(allow_local=True), context)

    await job.close()
    await job.close()

    assert context.closed


@pytest.mark.asyncio
async def test_click_rejects_non_link_controls() -> None:
    """Ordinary buttons cannot be clicked to trigger arbitrary page actions."""
    job = BrowserJob(BrowserRuntime(allow_local=True), FakeContext())
    page = FakePage()
    job._page = page
    job._elements["fogg-1"] = ObservedElement("fogg-1", "button", "Continue")

    with pytest.raises(BrowserPolicyError, match="links or search submit"):
        await job.click("fogg-1")

    assert not page.target.clicked


@pytest.mark.asyncio
async def test_click_allows_observed_link() -> None:
    """An observed link remains clickable for read-oriented research navigation."""
    job = BrowserJob(BrowserRuntime(allow_local=True), FakeContext())
    page = FakePage()
    job._page = page
    job._elements["fogg-1"] = ObservedElement("fogg-1", "link", "About")

    await job.click("fogg-1")

    assert page.target.clicked


@pytest.mark.asyncio
async def test_visual_click_is_limited_to_viewport_coordinates() -> None:
    job = BrowserJob(BrowserRuntime(allow_local=True), FakeContext())
    page = FakePage()
    clicked: list[tuple[int, int]] = []

    async def click(x: int, y: int) -> None:
        clicked.append((x, y))

    page.mouse.click = click
    job._page = page
    await job.click_at(1279, 719)
    with pytest.raises(BrowserPolicyError, match="outside the visible page"):
        await job.click_at(1280, 720)
    assert clicked == [(1279, 719)]


@pytest.mark.asyncio
async def test_visual_hotkey_rejects_arbitrary_key_sequences() -> None:
    job = BrowserJob(BrowserRuntime(allow_local=True), FakeContext())
    page = FakePage()
    pressed: list[str] = []

    async def press(key: str) -> None:
        pressed.append(key)

    page.keyboard.press = press
    job._page = page
    await job.press_hotkey("CTRL L")
    with pytest.raises(BrowserPolicyError, match="not allowed"):
        await job.press_hotkey("ALT F4")
    assert pressed == ["Control+L"]


@pytest.mark.asyncio
async def test_fill_rejects_password_fields() -> None:
    """Credential fields cannot be filled, even if an ID is supplied."""
    job = BrowserJob(BrowserRuntime(allow_local=True), FakeContext())
    page = FakePage()
    job._page = page
    job._elements["fogg-1"] = ObservedElement("fogg-1", "input", "Password", "password")

    with pytest.raises(BrowserPolicyError, match="text-entry"):
        await job.fill("fogg-1", "synthetic")

    assert not page.target.filled


@pytest.mark.asyncio
async def test_recording_is_started_and_finalized_on_close(tmp_path: Path) -> None:
    """Every job gets its own trace and video directory, finalized on close."""

    class Tracing:
        started = False
        saved = None

        async def start(self, **kwargs: object) -> None:
            assert kwargs == {"screenshots": True, "snapshots": True}
            self.started = True

        async def stop(self, *, path: str) -> None:
            self.saved = Path(path)

    class Page:
        def set_default_timeout(self, timeout: int) -> None:
            pass

        def on(self, *_args: object) -> None:
            pass

    class Context(FakeContext):
        def __init__(self) -> None:
            super().__init__()
            self.tracing = Tracing()

        async def route(self, *_args: object) -> None:
            pass

        async def new_page(self) -> Page:
            return Page()

    class Browser:
        def __init__(self) -> None:
            self.context = Context()
            self.options = {}

        async def new_context(self, **kwargs: object) -> Context:
            self.options = kwargs
            return self.context

    browser = Browser()
    runtime = BrowserRuntime(
        recording_dir=tmp_path,
        user_agent="Example Browser/1.0",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9", "DNT": "1"},
    )
    runtime._browser = browser
    job = await runtime.create_job()
    directory = Path(str(browser.options["record_video_dir"]))
    assert browser.options["user_agent"] == "Example Browser/1.0"
    assert browser.options["extra_http_headers"]["DNT"] == "1"
    assert (directory / "active").exists()
    assert browser.context.tracing.started
    await job.close()
    assert browser.context.tracing.saved == directory / "trace.zip"
    assert browser.context.closed
    assert not (directory / "active").exists()


@pytest.mark.asyncio
async def test_recording_failure_still_closes_browser_context(tmp_path: Path) -> None:
    class BrokenTracing:
        async def stop(self, *, path: str) -> None:
            raise OSError("disk unavailable")

    class Context(FakeContext):
        tracing = BrokenTracing()

    marker = tmp_path / "active"
    marker.touch()
    context = Context()
    job = BrowserJob(BrowserRuntime(), context, recording_dir=tmp_path)
    job._tracing = True
    with pytest.raises(OSError, match="disk unavailable"):
        await job.close()
    assert context.closed
    assert not marker.exists()


@pytest.mark.asyncio
async def test_persistent_context_uses_dedicated_profile_and_headed_chrome(
    tmp_path: Path,
) -> None:
    """Persistent profiles let the isolated worker retain its own browser session."""

    class Tracing:
        async def start(self, **_kwargs: object) -> None:
            pass

        async def stop(self, **_kwargs: object) -> None:
            pass

    class Page:
        def set_default_timeout(self, _timeout: int) -> None:
            pass

        def on(self, *_args: object) -> None:
            pass

    class Context(FakeContext):
        def __init__(self) -> None:
            super().__init__()
            self.tracing = Tracing()
            self.pages = [Page()]
            self.new_page_calls = 0

        async def route(self, *_args: object) -> None:
            pass

        async def new_page(self) -> Page:
            self.new_page_calls += 1
            return Page()

    class Chromium:
        def __init__(self) -> None:
            self.options: dict[str, object] = {}
            self.context = Context()

        async def launch_persistent_context(self, user_data_dir: str, **kwargs: object) -> Context:
            self.options = {"user_data_dir": user_data_dir, **kwargs}
            return self.context

    class Playwright:
        def __init__(self) -> None:
            self.chromium = Chromium()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    class Factory:
        def __init__(self, playwright: Playwright) -> None:
            self.playwright = playwright

        async def start(self) -> Playwright:
            return self.playwright

    playwright = Playwright()
    profile_dir = tmp_path / "dedicated-profile"
    runtime = BrowserRuntime(
        profile_dir=profile_dir,
        headless=False,
        browser_channel="chrome",
        playwright_factory=lambda: Factory(playwright),
    )

    await runtime.__aenter__()
    job = await runtime.create_job()

    assert playwright.chromium.options["user_data_dir"] == str(profile_dir)
    assert playwright.chromium.options["headless"] is False
    assert playwright.chromium.options["channel"] == "chrome"
    assert profile_dir.exists()
    assert job._page is playwright.chromium.context.pages[0]
    assert playwright.chromium.context.new_page_calls == 0
    await job.close()
    await runtime.close()
    assert playwright.stopped


@pytest.mark.asyncio
async def test_persistent_launch_failure_removes_active_recording_marker(
    tmp_path: Path,
) -> None:
    class Chromium:
        async def launch_persistent_context(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated browser launch failure")

    class Playwright:
        chromium = Chromium()

        async def stop(self) -> None:
            pass

    class Factory:
        async def start(self) -> Playwright:
            return Playwright()

    recording_dir = tmp_path / "recordings"
    runtime = BrowserRuntime(
        profile_dir=tmp_path / "profile",
        recording_dir=recording_dir,
        playwright_factory=Factory,
    )

    with pytest.raises(RuntimeError, match="simulated browser launch failure"):
        await runtime.__aenter__()

    assert list(recording_dir.glob("*/active")) == []
