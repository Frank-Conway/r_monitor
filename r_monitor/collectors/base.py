"""采集器统一接口。"""
from abc import ABC, abstractmethod
from typing import Any


class Collector(ABC):
    """所有采集器的公共基类：提供一致的采样与资源释放接口。"""

    @abstractmethod
    def sample(self, ts: float) -> Any:
        """采集一次快照；ts 为采样时刻（time.time() 秒）。"""

    def close(self) -> None:
        """释放底层资源；默认无操作，需要者重写。"""
        return None
