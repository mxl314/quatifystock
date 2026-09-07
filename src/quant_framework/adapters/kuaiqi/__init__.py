from ...core.interfaces import AdapterCapabilities


class KuaiqiAdapter:
    """快期适配器预留入口；接入具体 SDK 后实现 market 与 trading。"""

    capabilities = AdapterCapabilities()

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError("快期适配器尚未接入，请先确定具体 SDK 和接口版本")


__all__ = ["KuaiqiAdapter"]
