"""EverOS REST API 异步客户端。

封装 EverOS 的全部 REST API，提供统一的异步接口。
参考文档: https://github.com/EverMind-AI/EverOS
"""

from __future__ import annotations

import httpx
from typing import Any


class EverOSClient:
    """EverOS HTTP 客户端。

    Args:
        base_url: EverOS 服务地址，如 ``http://127.0.0.1:8765``
        timeout: 请求超时秒数，默认 30
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    # ─── 健康检查 ──────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """GET /health"""
        resp = await self._client.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    async def is_healthy(self) -> bool:
        try:
            data = await self.health()
            return data.get("status") == "ok"
        except Exception:
            return False

    # ─── 记忆写入 ──────────────────────────────────────────────────

    async def memory_add(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        app_id: str = "astrbot",
        project_id: str = "default",
    ) -> dict[str, Any]:
        """POST /api/v1/memory/add

        将消息批量注入记忆管道。EverOS 会积累到边界检测触发后自动提取记忆。

        Args:
            session_id: 会话标识
            messages: 消息列表，每条包含 sender_id/role/timestamp/content
            app_id: 应用标识
            project_id: 项目标识
        """
        payload = {
            "session_id": session_id,
            "app_id": app_id,
            "project_id": project_id,
            "messages": messages,
        }
        resp = await self._client.post(
            f"{self.base_url}/api/v1/memory/add", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def memory_flush(
        self,
        session_id: str,
        app_id: str = "astrbot",
        project_id: str = "default",
    ) -> dict[str, Any]:
        """POST /api/v1/memory/flush

        强制触发边界检测 + 记忆提取。
        """
        payload = {
            "session_id": session_id,
            "app_id": app_id,
            "project_id": project_id,
        }
        resp = await self._client.post(
            f"{self.base_url}/api/v1/memory/flush", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    # ─── 记忆检索 ──────────────────────────────────────────────────

    async def memory_search(
        self,
        query: str,
        user_id: str = "",
        app_id: str = "astrbot",
        project_id: str = "default",
        top_k: int = 5,
    ) -> dict[str, Any]:
        """POST /api/v1/memory/search

        混合（向量 + BM25）检索记忆。
        """
        payload = {
            "query": query,
            "user_id": user_id,
            "app_id": app_id,
            "project_id": project_id,
            "top_k": top_k,
        }
        resp = await self._client.post(
            f"{self.base_url}/api/v1/memory/search", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def memory_get(
        self,
        memory_type: str = "episode",
        app_id: str = "astrbot",
        project_id: str = "default",
        limit: int = 20,
        offset: int = 0,
        filters: dict | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/memory/get

        分页检索记忆。
        memory_type: episode / atomic_fact / agent_case / agent_skill / user_profile / foresight
        """
        payload: dict[str, Any] = {
            "memory_type": memory_type,
            "app_id": app_id,
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
        }
        if filters:
            payload["filters"] = filters
        resp = await self._client.post(
            f"{self.base_url}/api/v1/memory/get", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    # ─── 统计 ──────────────────────────────────────────────────────

    async def stats(
        self,
        user_id: str = "baizhi",
        app_id: str = "astrbot",
        project_id: str = "default",
    ) -> dict[str, int]:
        """获取各 memory_type 的条目计数。"""
        count_map: dict[str, int] = {}
        for mtype in ("episode", "profile", "agent_case", "agent_skill"):
            try:
                data = await self._client.post(
                    f"{self.base_url}/api/v1/memory/get",
                    json={
                        "memory_type": mtype,
                        "user_id": user_id,
                        "app_id": app_id,
                        "project_id": project_id,
                    },
                )
                result = data.json()
                d = result.get("data", {})
                total = d.get("total_count", len(d.get(mtype + "s", [])))
                count_map[mtype] = total
            except Exception:
                count_map[mtype] = -1
        return count_map
