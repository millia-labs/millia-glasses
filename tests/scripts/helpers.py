"""Fakes shared by the client-side tests: the glass as the host sees it, a voice that only records, and the scene's lines."""

from __future__ import annotations

from typing import Any

HELLO = "Hi, I'm in room 1013"
ASK = "The AC is a bit too noisy, and can I have some more towels?"


class _RecordingFrame:
    """The glass, as the host sees it: what was sent, and whether the link was closed."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, bytes]] = []
        self.disconnected = False
        self.stopped = False

    async def connect(self) -> None:
        pass

    async def upload_stdlua_libs(self, lib_names: list[str]) -> None:
        pass

    async def upload_frame_app(self, path: str) -> None:
        pass

    def register_data_response_handler(self, *_a: Any) -> None:
        pass

    def unregister_data_response_handler(self, *_a: Any) -> None:
        pass

    async def start_frame_app(self) -> None:
        pass

    async def stop_frame_app(self) -> None:
        self.stopped = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_message(self, code: int, payload: bytes) -> None:
        self.sent.append((code, payload))


class _Voice:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def __call__(self, text: str) -> None:
        self.spoken.append(text)
