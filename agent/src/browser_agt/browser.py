"""Bounded, read-oriented Playwright browser runtime for research and UI inspection."""

from __future__ import annotations

import asyncio
from io import BytesIO
import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, ImageChops


class BrowserPolicyError(ValueError):
    """Raised when a browser operation violates the runtime's safety policy."""


@dataclass(frozen=True, slots=True)
class ObservedElement:
    """A visible interactive element, addressable only in its observation snapshot."""

    element_id: str
    kind: str
    label: str
    input_type: str | None = None


@dataclass(frozen=True, slots=True)
class PageObservation:
    """Visible page information and the interactive elements available to the agent."""

    url: str
    title: str
    text: str
    elements: tuple[ObservedElement, ...]
    screenshot: bytes | None = None
    scroll_target: str = "document"
    scroll_top: float = 0
    scroll_height: float = 0
    client_height: float = 0
    at_scroll_end: bool = False
    scroll_position_changed: bool | None = None
    screenshot_changed: bool | None = None


_SCROLL_MARK_SCRIPT = """({x, y, marker}) => {
  const root = document.scrollingElement || document.documentElement;
  let target = document.elementFromPoint(x, y);
  while (target && target !== root) {
    const style = getComputedStyle(target);
    if (['auto', 'scroll', 'overlay'].includes(style.overflowY) &&
        target.scrollHeight > target.clientHeight + 1) break;
    target = target.parentElement;
  }
  const isDocument = !target || target === root || target === document.body ||
    target === document.documentElement;
  target = isDocument ? root : target;
  target.setAttribute('data-fogg-scroll-target', marker);
  return {
    marker,
    target: isDocument ? 'document' : 'element',
    scroll_top: target.scrollTop,
    scroll_height: target.scrollHeight,
    client_height: target.clientHeight,
    at_end: target.scrollTop + target.clientHeight >= target.scrollHeight - 2
  };
}"""

_SCROLL_STATE_SCRIPT = """(marker) => {
  const root = document.scrollingElement || document.documentElement;
  let target = root, kind = 'document', markerFound = false;
  if (marker) {
    target = [...document.querySelectorAll('[data-fogg-scroll-target]')]
      .find(el => el.getAttribute('data-fogg-scroll-target') === marker);
    markerFound = Boolean(target);
    if (!target) target = root;
    else kind = target === root ? 'document' : 'element';
    if (markerFound) target.removeAttribute('data-fogg-scroll-target');
  }
  return {
    target: kind,
    marker_found: markerFound,
    scroll_top: target.scrollTop,
    scroll_height: target.scrollHeight,
    client_height: target.clientHeight,
    at_end: target.scrollTop + target.clientHeight >= target.scrollHeight - 2
  };
}"""


def _screenshot_shifted(previous: bytes | None, current: bytes) -> bool | None:
    """Detect meaningful viewport changes while ignoring tiny animated regions."""
    if previous is None:
        return None
    try:
        size = (128, 72)
        before = (
            Image.open(BytesIO(previous)).convert("RGB").resize(size, Image.Resampling.BILINEAR)
        )
        after = Image.open(BytesIO(current)).convert("RGB").resize(size, Image.Resampling.BILINEAR)
        difference = ImageChops.difference(before, after).convert("L")
        changed_pixels = difference.point(lambda value: 255 if value >= 24 else 0).histogram()[255]
        return changed_pixels / (size[0] * size[1]) >= 0.01
    except (OSError, ValueError):
        return None


_OBSERVE_SCRIPT = """() => {
  const snapshot = Math.random().toString(36).slice(2);
  const visible = (el) => {
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' &&
      Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const candidates = [...document.querySelectorAll('a[href],button,input,textarea,select,[role="button"],[role="link"]')].filter(visible).slice(0, 100);
  return candidates.map((el, i) => {
    const id = `fogg-${snapshot}-${i + 1}`;
    el.setAttribute('data-fogg-element', id);
    const form = el.form || el.closest('form');
    const searchForm = form && (form.matches('[role="search"]') || form.querySelector('input[type="search"],[role="searchbox"]'));
    const kind = el.matches('a[href]') ? 'link' :
      ((el.matches('button[type="submit"],input[type="submit"]') && searchForm) ? 'search_submit' :
        (el.getAttribute('role') || el.tagName.toLowerCase()));
    const autocomplete = (el.getAttribute('autocomplete') || '').toLowerCase();
    const credentialHint = `${el.getAttribute('type') || ''} ${autocomplete} ${el.getAttribute('name') || ''} ${el.id} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('placeholder') || ''}`.toLowerCase();
    const sensitive = el.matches('input,textarea') && ['password','current-password','new-password','username','one-time-code',
      'cc-number','cc-csc','cc-exp','transaction-amount','security-code','passcode'].some((token) => credentialHint.includes(token));
    return {id, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', kind,
      label: (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().slice(0, 200),
      type: el.getAttribute('type') || '', sensitive};
  });
}"""


class BrowserRuntime:
    """Own a browser process and create isolated, bounded browser jobs.

    DNS resolution is checked before navigation and for intercepted requests, but this
    cannot prevent DNS rebinding between the check and Chromium's connection. GET requests
    can also have side effects on remote sites. Production deployments still need host or
    container egress controls and must isolate browser processes at the deployment level.

    Args:
        action_limit: Maximum read or interaction operations allowed per job.
        timeout_ms: Playwright timeout applied to each operation.
        allow_local: Permit private/local destinations for explicitly isolated tests.
        playwright_factory: Optional async factory returning Playwright (useful for tests).
    """

    def __init__(
        self,
        *,
        action_limit: int = 30,
        timeout_ms: int = 10_000,
        allow_local: bool = False,
        playwright_factory: Callable[[], Any] | None = None,
        proxy_server: str | None = None,
        recording_dir: str | Path | None = None,
        profile_dir: str | Path | None = None,
        headless: bool = True,
        browser_channel: str | None = None,
        user_agent: str | None = None,
        extra_http_headers: dict[str, str] | None = None,
    ) -> None:
        if action_limit < 1 or timeout_ms < 1:
            raise ValueError("action_limit and timeout_ms must be positive")
        if user_agent and ("\r" in user_agent or "\n" in user_agent):
            raise ValueError("User agent must not contain newlines")
        self.action_limit = action_limit
        self.timeout_ms = timeout_ms
        self.allow_local = allow_local
        self._playwright_factory = playwright_factory
        self.proxy_server = proxy_server
        self.recording_dir = Path(recording_dir) if recording_dir is not None else None
        self.profile_dir = Path(profile_dir) if profile_dir is not None else None
        self.headless = headless
        self.browser_channel = browser_channel
        self.user_agent = user_agent
        self.extra_http_headers = extra_http_headers
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._persistent_context: Any | None = None
        self._persistent_recording_dir: Path | None = None
        self._jobs: set[BrowserJob] = set()

    async def __aenter__(self) -> BrowserRuntime:
        if self._browser is not None:
            raise RuntimeError("browser runtime is already started")
        if self._playwright_factory is None:
            from playwright.async_api import async_playwright

            factory = async_playwright
        else:
            factory = self._playwright_factory
        self._playwright = await factory().start()
        try:
            launch_options = {
                "headless": self.headless,
                "chromium_sandbox": True,
                "proxy": (
                    {"server": self.proxy_server, "bypass": "<-loopback>"}
                    if self.proxy_server
                    else None
                ),
                "args": [
                    "--disable-quic",
                    "--disable-gpu",
                    "--num-raster-threads=2",
                    "--renderer-process-limit=4",
                ],
            }
            if self.profile_dir is None:
                self._browser = await self._playwright.chromium.launch(
                    channel=self.browser_channel, **launch_options
                )
            else:
                self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory = (
                    self.recording_dir / uuid4().hex if self.recording_dir is not None else None
                )
                if directory is not None:
                    directory.mkdir(parents=True, mode=0o700)
                    (directory / "active").touch(mode=0o600)
                self._persistent_recording_dir = directory
                context_options: dict[str, Any] = {
                    "accept_downloads": False,
                    **launch_options,
                }
                if self.browser_channel:
                    context_options["channel"] = self.browser_channel
                if self.user_agent:
                    context_options["user_agent"] = self.user_agent
                if self.extra_http_headers:
                    context_options["extra_http_headers"] = self.extra_http_headers
                if directory is not None:
                    context_options["record_video_dir"] = str(directory)
                self._persistent_context = (
                    await self._playwright.chromium.launch_persistent_context(
                        str(self.profile_dir), **context_options
                    )
                )
        except BaseException:
            if self._persistent_recording_dir is not None:
                (self._persistent_recording_dir / "active").unlink(missing_ok=True)
                self._persistent_recording_dir = None
            await self._playwright.stop()
            self._playwright = None
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.close()

    async def create_job(self) -> BrowserJob:
        """Create an independent browser context and page for one job.

        Returns:
            A newly initialized browser job.
        """
        if self._browser is None and self._persistent_context is None:
            raise RuntimeError("use BrowserRuntime as an async context manager first")
        directory = self._persistent_recording_dir
        if directory is None and self.recording_dir is not None:
            directory = self.recording_dir / uuid4().hex
        if directory is not None:
            if not directory.exists():
                directory.mkdir(parents=True, mode=0o700)
                (directory / "active").touch(mode=0o600)
        options: dict[str, Any] = {"accept_downloads": False}
        if self.user_agent:
            options["user_agent"] = self.user_agent
        if self.extra_http_headers:
            options["extra_http_headers"] = self.extra_http_headers
        if directory is not None:
            options["record_video_dir"] = str(directory)
        try:
            if self._persistent_context is not None:
                context = self._persistent_context
            else:
                assert self._browser is not None
                context = await self._browser.new_context(**options)
        except BaseException:
            if directory is not None:
                (directory / "active").unlink(missing_ok=True)
            raise
        job = BrowserJob(self, context, recording_dir=directory)
        try:
            if directory is not None:
                await context.tracing.start(screenshots=True, snapshots=True)
                job._tracing = True
            await context.route("**/*", job._guard_request)
            pages = getattr(context, "pages", ())
            page = pages[0] if pages else await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            page.on("popup", lambda popup: asyncio.create_task(popup.close()))
            job._page = page
            if directory is not None:
                job._preview_task = asyncio.create_task(job._record_preview())
        except BaseException:
            await job.close()
            raise
        self._jobs.add(job)
        return job

    async def close(self) -> None:
        """Close all active jobs, the browser, and Playwright, even after cancellation."""
        jobs = tuple(self._jobs)
        if jobs:
            await asyncio.gather(*(job.close() for job in jobs), return_exceptions=True)
        browser, playwright = self._browser, self._playwright
        persistent_context = self._persistent_context
        self._browser = None
        self._persistent_context = None
        self._playwright = None
        if browser is not None:
            try:
                await browser.close()
            finally:
                if playwright is not None:
                    await playwright.stop()
        if persistent_context is not None:
            try:
                await persistent_context.close()
            finally:
                if self._persistent_recording_dir is not None:
                    (self._persistent_recording_dir / "active").unlink(missing_ok=True)
                    self._persistent_recording_dir = None
                if playwright is not None:
                    await playwright.stop()
        elif browser is None and playwright is not None:
            await playwright.stop()

    async def _validate_url(self, url: str) -> None:
        if len(url) > 4_096:
            raise BrowserPolicyError("URL exceeds the maximum length")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if (
                parsed.scheme not in {"http", "https"}
                or not host
                or parsed.username
                or parsed.password
            ):
                raise BrowserPolicyError("only credential-free HTTP(S) URLs are allowed")
            if self.allow_local:
                return
            if host.lower().rstrip(".") in {"localhost", "localhost.localdomain"}:
                raise BrowserPolicyError("local destinations are blocked")
            try:
                addresses = {ipaddress.ip_address(host)}
            except ValueError:
                loop = asyncio.get_running_loop()
                results = await loop.getaddrinfo(
                    host,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
                addresses = {ipaddress.ip_address(result[4][0]) for result in results}
            if not addresses or any(not address.is_global for address in addresses):
                raise BrowserPolicyError("private or non-public destinations are blocked")
        except (socket.gaierror, UnicodeError) as exc:
            raise BrowserPolicyError("destination could not be safely resolved") from exc


class BrowserJob:
    """A single isolated page with snapshot-scoped interaction IDs."""

    def __init__(
        self, runtime: BrowserRuntime, context: Any, *, recording_dir: Path | None = None
    ) -> None:
        self._runtime = runtime
        self._context = context
        self._page: Any | None = None
        self._actions = 0
        self._elements: dict[str, ObservedElement] = {}
        self._closed = False
        self._recording_dir = recording_dir
        self._tracing = False
        self._preview_task: asyncio.Task[None] | None = None
        self._last_observation_screenshot: bytes | None = None
        self._pending_scroll: dict[str, Any] | None = None

    async def _record_preview(self) -> None:
        """Publish a bounded, atomic latest frame for the local live viewer."""
        assert self._recording_dir is not None
        while True:
            try:
                frame = await self._page_required().screenshot(
                    type="png", timeout=self._runtime.timeout_ms
                )
                temporary = self._recording_dir / "latest.tmp"
                await asyncio.to_thread(temporary.write_bytes, frame)
                await asyncio.to_thread(temporary.replace, self._recording_dir / "latest.png")
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Navigation can temporarily make the page unavailable.
            await asyncio.sleep(0.5)

    async def _guard_request(self, route: Any) -> None:
        request = route.request
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            await route.abort()
            return
        try:
            await self._runtime._validate_url(request.url)
        except BrowserPolicyError:
            await route.abort()
            return
        await route.continue_()

    def _page_required(self) -> Any:
        if self._closed or self._page is None:
            raise RuntimeError("browser job is closed")
        return self._page

    def _consume_action(self) -> Any:
        page = self._page_required()
        if self._actions >= self._runtime.action_limit:
            raise BrowserPolicyError("browser job action limit reached")
        self._actions += 1
        return page

    async def navigate(self, url: str) -> None:
        """Navigate to a public HTTP(S) page, subject to the job's action limit."""
        page = self._consume_action()
        self._elements.clear()
        await self._runtime._validate_url(url)
        await page.goto(url, wait_until="domcontentloaded", timeout=self._runtime.timeout_ms)

    async def observe(self) -> PageObservation:
        """Read visible text and issue IDs for visible links and interactive controls."""
        page = self._consume_action()
        elements = await page.evaluate(_OBSERVE_SCRIPT)
        self._elements = {
            item["id"]: ObservedElement(
                element_id=item["id"],
                kind=item["kind"],
                label=item["label"],
                input_type=item["type"] or None,
            )
            for item in elements
            if not item["sensitive"]
        }
        pending_scroll = self._pending_scroll
        scroll_state = await page.evaluate(
            _SCROLL_STATE_SCRIPT,
            pending_scroll["marker"] if pending_scroll else None,
        )
        screenshot = await page.screenshot(
            type="jpeg", quality=65, full_page=False, timeout=self._runtime.timeout_ms
        )
        screenshot_changed = _screenshot_shifted(self._last_observation_screenshot, screenshot)
        self._last_observation_screenshot = screenshot
        self._pending_scroll = None
        scroll_position_changed = None
        if pending_scroll and scroll_state.get("marker_found"):
            scroll_position_changed = (
                abs(float(scroll_state["scroll_top"]) - float(pending_scroll["scroll_top"])) > 1
            )
        return PageObservation(
            url=page.url,
            title=await page.title(),
            text=(await page.locator("body").inner_text(timeout=self._runtime.timeout_ms))[:20_000],
            elements=tuple(self._elements.values()),
            screenshot=screenshot,
            scroll_target=scroll_state["target"],
            scroll_top=float(scroll_state["scroll_top"]),
            scroll_height=float(scroll_state["scroll_height"]),
            client_height=float(scroll_state["client_height"]),
            at_scroll_end=bool(scroll_state["at_end"]),
            scroll_position_changed=scroll_position_changed,
            screenshot_changed=screenshot_changed,
        )

    async def click_at(self, x: int, y: int) -> None:
        """Click a visible viewport coordinate from the current screenshot."""
        page = self._consume_action()
        size = page.viewport_size
        if size is None or not (0 <= x < size["width"] and 0 <= y < size["height"]):
            raise BrowserPolicyError("click coordinate is outside the visible page")
        await page.mouse.click(x, y)

    async def type_text(self, value: str) -> None:
        """Type plain text into the currently focused control."""
        page = self._consume_action()
        if len(value) > 2000:
            raise BrowserPolicyError("typed text exceeds the maximum length")
        await page.keyboard.insert_text(value)

    async def press_hotkey(self, key: str) -> None:
        """Press a small, validated keyboard shortcut."""
        page = self._consume_action()
        modifiers = {"CTRL", "ALT", "SHIFT", "META"}
        keys = {
            "TAB",
            "ENTER",
            "ESC",
            "BACKSPACE",
            "DELETE",
            "SPACE",
            "ARROWUP",
            "ARROWDOWN",
            "ARROWLEFT",
            "ARROWRIGHT",
            "HOME",
            "END",
            "PAGEUP",
            "PAGEDOWN",
        }
        parts = key.upper().split()
        if (
            not 1 <= len(parts) <= 3
            or len(set(parts) & modifiers) > 2
            or any(
                part not in modifiers and part not in keys and not re.fullmatch(r"[A-Z0-9]", part)
                for part in parts
            )
        ):
            raise BrowserPolicyError("keyboard shortcut is not allowed")
        playwright_names = {
            "CTRL": "Control",
            "ALT": "Alt",
            "SHIFT": "Shift",
            "META": "Meta",
            "ARROWUP": "ArrowUp",
            "ARROWDOWN": "ArrowDown",
            "ARROWLEFT": "ArrowLeft",
            "ARROWRIGHT": "ArrowRight",
            "PAGEUP": "PageUp",
            "PAGEDOWN": "PageDown",
        }
        await page.keyboard.press(
            "+".join(playwright_names.get(part, part.title()) for part in parts)
        )

    async def scroll_at(self, x: int, y: int, direction: str) -> None:
        """Scroll the visible page in a bounded direction."""
        page = self._consume_action()
        size = page.viewport_size
        if size is None or not (0 <= x < size["width"] and 0 <= y < size["height"]):
            raise BrowserPolicyError("scroll coordinate is outside the visible page")
        distances = {"up": (0, -600), "down": (0, 600), "left": (-600, 0), "right": (600, 0)}
        if direction not in distances:
            raise BrowserPolicyError("scroll direction is invalid")
        marker = f"fogg-scroll-{uuid4().hex}"
        self._pending_scroll = await page.evaluate(
            _SCROLL_MARK_SCRIPT, {"x": x, "y": y, "marker": marker}
        )
        await page.mouse.move(x, y)
        await page.mouse.wheel(*distances[direction])

    async def wait(self, seconds: float = 2) -> None:
        """Wait briefly for a visual page update."""
        self._consume_action()
        if not 0 < seconds <= 5:
            raise BrowserPolicyError("wait duration must be between 0 and 5 seconds")
        await asyncio.sleep(seconds)

    async def click(self, element_id: str) -> None:
        """Click an element ID from the latest observation; stale IDs are rejected."""
        page = self._consume_action()
        element = self._elements.get(element_id)
        if element is None:
            raise BrowserPolicyError("element ID is missing or stale; observe the page again")
        if element.kind not in {"link", "search_submit"}:
            raise BrowserPolicyError("only observed links or search submit controls can be clicked")
        await page.locator(f'[data-fogg-element="{element_id}"]').click(
            timeout=self._runtime.timeout_ms
        )
        self._elements.clear()

    async def fill(self, element_id: str, value: str) -> None:
        """Fill an observed text-entry control; form submission remains blocked."""
        page = self._consume_action()
        if len(value) > 10_000:
            raise BrowserPolicyError("fill value exceeds the maximum length")
        element = self._elements.get(element_id)
        if element is None:
            raise BrowserPolicyError("element ID is missing or stale; observe the page again")
        if element.kind not in {"input", "textarea"} or element.input_type in {
            "submit",
            "button",
            "image",
            "file",
            "hidden",
            "password",
        }:
            raise BrowserPolicyError("only observed text-entry controls can be filled")
        await page.locator(f'[data-fogg-element="{element_id}"]').fill(
            value, timeout=self._runtime.timeout_ms
        )

    async def back(self) -> None:
        """Return to the previous history entry."""
        page = self._consume_action()
        self._elements.clear()
        await page.go_back(wait_until="domcontentloaded", timeout=self._runtime.timeout_ms)

    async def screenshot(self) -> bytes:
        """Capture the current viewport as PNG bytes."""
        page = self._consume_action()
        return await page.screenshot(type="png", full_page=False, timeout=self._runtime.timeout_ms)

    async def close(self) -> None:
        """Close this job's isolated context and detach it from the runtime."""
        if self._closed:
            return
        self._closed = True
        self._elements.clear()
        try:
            if self._preview_task is not None:
                self._preview_task.cancel()
                await asyncio.gather(self._preview_task, return_exceptions=True)
            try:
                if self._tracing and self._recording_dir is not None:
                    await self._context.tracing.stop(path=str(self._recording_dir / "trace.zip"))
            finally:
                await self._context.close()
        finally:
            if self._recording_dir is not None:
                (self._recording_dir / "active").unlink(missing_ok=True)
            self._runtime._jobs.discard(self)
