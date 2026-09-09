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

    def require_capability(self, channel: str, capability: str) -> ChannelAdapter:
        adapter = self.get(channel)
        if capability not in adapter.capabilities():
            raise NotImplementedError(f"channel {channel} does not support {capability}")
        return adapter
