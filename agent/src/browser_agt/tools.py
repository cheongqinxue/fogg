"""Async, narrowly scoped research tools bound to one browser job."""

from __future__ import annotations

import json
import base64
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from browser_agt.agent import ResearchSource
from browser_agt.duplex import BrowserMasterChannel

if TYPE_CHECKING:
    from browser_agt.browser import BrowserJob, PageObservation


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(_Input):
    query: str = Field(min_length=1, max_length=500, description="Web search query.")


class OpenInput(_Input):
    url: str = Field(min_length=1, max_length=2048, description="Public HTTP(S) page URL.")


class ElementInput(_Input):
    element_id: str = Field(
        min_length=1, max_length=50, description="Element ID from the latest page observation."
    )


class FillInput(ElementInput):
    value: str = Field(max_length=1000, description="Text to enter into the field.")


class EmptyInput(_Input):
    pass


class ReadObservationsInput(_Input):
    observation_ids: list[str] = Field(
        min_length=1,
        max_length=2,
        description="One or two observation IDs from earlier browser tool results.",
    )


class AskMasterInput(_Input):
    question: str = Field(
        min_length=1,
        max_length=1200,
        description="A concise question for the master agent when its trip context or judgment is needed.",
    )


class PointInput(_Input):
    x: int = Field(ge=0, le=4096, description="Horizontal coordinate from the current screenshot.")
    y: int = Field(ge=0, le=4096, description="Vertical coordinate from the current screenshot.")


class TypeInput(_Input):
    value: str = Field(max_length=2000, description="Text to type into the focused field.")


class HotkeyInput(_Input):
    key: str = Field(
        min_length=1, max_length=40, description="Allowed key or shortcut, such as CTRL L or ENTER."
    )


class ScrollInput(PointInput):
    direction: str = Field(description="Scroll direction: up, down, left, or right.")


class WaitInput(_Input):
    seconds: float = Field(default=2, gt=0, le=5, description="Seconds to wait, up to 5.")


def create_browser_tools(
    job: BrowserJob,
    sources: list[ResearchSource],
    master_channel: BrowserMasterChannel | None = None,
) -> list[StructuredTool]:
    """Bind browser actions to one isolated job and its observed source list.

    Args:
        job: The job owning the current page and action budget.
        sources: A per-task list receiving source metadata.

    Returns:
        Tools with explicit input schemas suitable for model tool calling.
    """

    observations: dict[str, PageObservation] = {}
    latest_observation_id: str | None = None

    async def describe(observation: PageObservation) -> str:
        nonlocal latest_observation_id
        observation_id = uuid4().hex
        observations[observation_id] = observation
        latest_observation_id = observation_id
        url = observation.url
        if urlsplit(url).scheme in {"http", "https"} and urlsplit(url).hostname != "duckduckgo.com":
            if not any(source.url == url for source in sources):
                sources.append(
                    ResearchSource(url=url, title=observation.title, observed_at=datetime.now(UTC))
                )
        payload = asdict(observation)
        screenshot = payload.pop("screenshot", None)
        if screenshot is not None:
            payload["screenshot"] = base64.b64encode(screenshot).decode("ascii")
        if master_channel is not None:
            instruction = await master_channel.exchange(
                kind="browser_update",
                payload={
                    "url": observation.url,
                    "title": observation.title,
                    "text": observation.text[:4000],
                    "scroll": {
                        "at_end": observation.at_scroll_end,
                        "position_changed": observation.scroll_position_changed,
                        "screenshot_changed": observation.screenshot_changed,
                    },
                },
            )
            payload["master_guidance"] = instruction
        return json.dumps({"observation_id": observation_id, **payload}, ensure_ascii=False)

    async def read_observations(observation_ids: list[str]) -> str:
        results = []
        for observation_id in observation_ids:
            observation = observations.get(observation_id)
            if observation is None:
                results.append(
                    {"observation_id": observation_id, "error": "Unknown observation ID."}
                )
                continue
            is_current_page = observation_id == latest_observation_id
            results.append(
                {
                    "observation_id": observation_id,
                    "url": observation.url,
                    "title": observation.title,
                    "text": observation.text,
                    "screenshot": (
                        base64.b64encode(observation.screenshot).decode("ascii")
                        if observation.screenshot is not None
                        else None
                    ),
                    "elements": (
                        [asdict(element) for element in observation.elements]
                        if is_current_page
                        else []
                    ),
                    "is_current_page": is_current_page,
                }
            )
        return json.dumps({"observations": results}, ensure_ascii=False)

    async def search_web(query: str) -> str:
        await job.navigate("https://duckduckgo.com/?" + urlencode({"q": query, "ia": "web"}))
        return await describe(await job.observe())

    async def open_page(url: str) -> str:
        await job.navigate(url)
        return await describe(await job.observe())

    async def observe_page() -> str:
        return await describe(await job.observe())

    async def click_element(element_id: str) -> str:
        await job.click(element_id)
        return await describe(await job.observe())

    async def fill_field(element_id: str, value: str) -> str:
        await job.fill(element_id, value)
        return await describe(await job.observe())

    async def go_back() -> str:
        await job.back()
        return await describe(await job.observe())

    async def click_at(x: int, y: int) -> str:
        await job.click_at(x, y)
        return await describe(await job.observe())

    async def type_text(value: str) -> str:
        await job.type_text(value)
        return await describe(await job.observe())

    async def press_hotkey(key: str) -> str:
        await job.press_hotkey(key)
        return await describe(await job.observe())

    async def scroll_at(x: int, y: int, direction: str) -> str:
        await job.scroll_at(x, y, direction)
        return await describe(await job.observe())

    async def wait_for_update(seconds: float = 2) -> str:
        await job.wait(seconds)
        return await describe(await job.observe())

    async def ask_master(question: str) -> str:
        if master_channel is None:
            return "Master guidance is unavailable; continue using the research task and observed evidence."
        return await master_channel.exchange(
            kind="browser_guidance_request", payload={"question": question}
        )

    definitions: list[tuple[str, str, Any, type[BaseModel]]] = [
        (
            "browser_search",
            "Search the public web for pages relevant to the task.",
            search_web,
            SearchInput,
        ),
        ("browser_open", "Open a public URL and observe its contents.", open_page, OpenInput),
        (
            "browser_observe",
            "Observe the current page and its actionable elements.",
            observe_page,
            EmptyInput,
        ),
        (
            "browser_click",
            "Click an element ID from the most recent observation.",
            click_element,
            ElementInput,
        ),
        (
            "browser_fill",
            "Fill an observed text input with a search or filter value.",
            fill_field,
            FillInput,
        ),
        ("browser_back", "Return to the previous page and observe it.", go_back, EmptyInput),
        (
            "browser_click_at",
            "Click a coordinate from the current screenshot.",
            click_at,
            PointInput,
        ),
        ("browser_type_text", "Type text into the currently focused field.", type_text, TypeInput),
        ("browser_hotkey", "Press an allowed keyboard shortcut.", press_hotkey, HotkeyInput),
        ("browser_scroll_at", "Scroll at a visible screenshot coordinate.", scroll_at, ScrollInput),
        (
            "browser_wait",
            "Wait briefly for the page to update, then take a new screenshot.",
            wait_for_update,
            WaitInput,
        ),
        (
            "browser_read_observations",
            "Read up to two stored observations by ID; historical controls are not actionable.",
            read_observations,
            ReadObservationsInput,
        ),
        (
            "browser_ask_master",
            "Ask the master agent for guidance using the user's trip context or a judgment call.",
            ask_master,
            AskMasterInput,
        ),
    ]
    return [
        StructuredTool.from_function(
            coroutine=func, name=name, description=description, args_schema=schema
        )
        for name, description, func, schema in definitions
    ]
