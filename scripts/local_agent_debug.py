import json
import logging
from collections.abc import Iterator

import httpx
from httpx import Timeout

import sseclient
from utils.settings import get_settings

DEFAULT_USER = "default_01"

logger = logging.getLogger(__name__)


def format_as_other(text: str, after="") -> str:
    return f"\033[1;33m{text}{after}"


def print_format_as_assistant(stream: Iterator):
    """Use Red foreground"""
    # return f"\033[0;31m {text} \033[0m"
    print("\033[0;31m", end="")
    for item in stream:
        package = json.loads(item.data)
        if package.get("type", "") == "assistant_delta":
            token = package["delta"]
            print(f"{token}", end="")
        else:
            print("\n\n" + format_as_other(str(package), after="\033[0m\n"))

    print("\033[0m")


def format_as_asst(text: str) -> str:
    """Use Red foreground"""
    return f"\033[0;31m {text} \033[0m"


def format_as_user(text: str) -> str:
    """Use Green foreground"""
    return f"\033[0;32m {text} \033[0m"


def format_as_main(text: str) -> str:
    return f"\033[0;34m {text} \033[0m"


def stream_one_turn(client: httpx.Client, query: str):
    with client.stream(
        "POST",
        f"/v1/users/{DEFAULT_USER}/chat/stream",
        json={"message": query},
    ) as s:
        print_format_as_assistant(sseclient.SSEClient(s.iter_bytes()).events())


def main():
    with httpx.Client(
        base_url=get_settings().agent_api_base_url, timeout=Timeout(30, connect=5, read=20)
    ) as client:
        response = client.get(f"/v1/users/{DEFAULT_USER}/messages")
        messages = response.json()["messages"]
        print(format_as_main("History =====================\n"))
        for message in messages:
            if message["role"] == "user":
                print(format_as_user(message["text"]))
            elif message["role"] == "assistant":
                print(format_as_asst(message["text"]))
        print(format_as_main("------------------------------\n\n"))
        query = input("msg: \033[0;32m")
        while query != "/exit":
            if query == "/reset":
                client.post("/v1/dev/reset", json={"user_id": DEFAULT_USER})
            print()
            stream_one_turn(client, query)
            query = input("msg: \033[0;32m")
        print(format_as_main("---------"))


if __name__ == "__main__":
    main()
