from .contracts import ChannelAdapter


class ChannelRegistry:
    def __init__(self):
        self._items = {}

    def register(self, adapter: ChannelAdapter) -> None:
        if adapter.channel in self._items:
            raise ValueError("channel already registered")
        self._items[adapter.channel] = adapter

    def get(self, channel: str) -> ChannelAdapter:
        try:
            return self._items[channel]
        except KeyError as exc:
            raise ValueError("channel unavailable") from exc
