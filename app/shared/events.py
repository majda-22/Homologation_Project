"""Event bus applicatif simple et synchrone."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, DefaultDict, TypeVar

Event = TypeVar("Event")
EventHandler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: DefaultDict[type[Any], list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], handler: Callable[[Event], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            handler(event)
