"""会话抽象基类。

两种实现共享同一接口：
- ``SubprocessSession`` — 启动 ``vivado -mode tcl`` 无头子进程（CI / 批处理友好）
- ``GuiSession`` — Popen ``vivado -mode gui`` 或 attach 已有 GUI，通过 TCP 通信

工具层代码通过 BaseSession 接口操作会话，不感知具体实现。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from enum import Enum

from vivado_mcp.vivado.tcl_utils import TclResult

logger = logging.getLogger(__name__)

# 该变量"存在即生效"(值为 0 也一样):cmd 不再在当前目录找 .bat,
# Vivado 2019.1 的 launch_simulation 调 compile.bat 不带路径,于是必挂。
# Claude 客户端等父进程会注入它,MCP spawn 的 Vivado 原样继承。
_CURDIR_POLICY_VAR = "NoDefaultCurrentDirectoryInExePath"


def vivado_child_env() -> dict[str, str] | None:
    """返回 spawn Vivado 用的环境;无需改动时返回 None(= 继承父进程)。

    仅 Windows 上移除 ``NoDefaultCurrentDirectoryInExePath``(大小写不敏感匹配),
    其余变量原样保留,与从开始菜单启动 Vivado 的环境一致。
    """
    if sys.platform != "win32":
        return None
    target = _CURDIR_POLICY_VAR.upper()
    if not any(k.upper() == target for k in os.environ):
        return None
    env = {k: v for k, v in os.environ.items() if k.upper() != target}
    logger.info(
        "已从 Vivado 子进程环境移除 %s(该变量存在即阻止 cmd 在当前目录找 .bat,"
        "launch_simulation 会挂)",
        _CURDIR_POLICY_VAR,
    )
    return env


class SessionState(str, Enum):
    """会话状态枚举。"""
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DEAD = "dead"  # D4: socket 断开 / 进程崩溃 / 用户关闭 GUI


class BaseSession(ABC):
    """Vivado 会话抽象基类。

    子类必须实现 ``start``、``execute``、``stop``、``is_alive``。
    """

    def __init__(self, vivado_path: str, session_id: str = "default"):
        self.vivado_path = vivado_path
        self.session_id = session_id
        self._state: SessionState = SessionState.STOPPED
        self._start_time: float | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def uptime_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """会话是否仍可响应命令。"""

    @property
    @abstractmethod
    def mode(self) -> str:
        """会话类型标识：``"tcl"`` / ``"gui"`` / ``"attach"``。"""

    @abstractmethod
    async def start(self, timeout: float = 120.0) -> str:
        """启动或连接 Vivado，返回启动信息。"""

    @abstractmethod
    async def execute(
        self,
        tcl_command: str,
        timeout: float = 120.0,
    ) -> TclResult:
        """执行一条 Tcl 命令并返回结果。"""

    @abstractmethod
    async def stop(self, timeout: float = 10.0) -> None:
        """关闭会话。"""

    def status_dict(self) -> dict:
        """返回会话状态信息字典。"""
        d = {
            "session_id": self.session_id,
            "mode": self.mode,
            "state": self._state.value,
            "vivado_path": self.vivado_path,
            "is_alive": self.is_alive,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }
        # 可选字段:GUI session 暴露端口和 external attach 标志,让 list_sessions
        # / 调试时一眼看出命令会落到哪个 Vivado 实例
        port = getattr(self, "connected_port", None)
        if port is not None:
            d["port"] = port
        if getattr(self, "attached_external", False):
            d["attached_external"] = True
        return d
