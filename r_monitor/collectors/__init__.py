"""采集器集合。"""
from .base import Collector
from .cpu import CpuCollector
from .gpu import GpuCollector
from .network import NetworkCollector

__all__ = ["Collector", "CpuCollector", "GpuCollector", "NetworkCollector"]
