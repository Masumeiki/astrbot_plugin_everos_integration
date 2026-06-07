"""
EverOS for AstrBot — 为 AstrBot 接入 GitHub 上的 EverOS 自进化记忆引擎。

让 AstrBot 的 Agent 能直接使用 EverOS 的记忆写入/检索能力，
通过 Plugin Pages 管理面板监控服务状态。

功能：
- 连接 EverOS REST API（独立容器部署）
- 注册 LLM 工具：everos_memorize / everos_recall
- Plugin Page 管理面板：状态监控 + 记忆统计 + 快速测试
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
from quart import jsonify, request

from .core.config_manager import ConfigManager
from .core.everos_client import EverOSClient
from .core.standalone_server import StandaloneServer
from .tools.everos_tools import EverOSMemorizeTool, EverOSRecallTool

PLUGIN_NAME = "astrbot_plugin_everos_integration"


@register(
    PLUGIN_NAME,
    "白芷 & Masumeiki",
    "为 AstrBot 集成 EverOS 自进化记忆引擎，让 Agent 拥有长期记忆与自我学习能力",
    "1.0.1",
    "https://github.com/Masumeiki/astrbot_plugin_everos_integration",
)
class EverOSIntegrationPlugin(Star):
    """EverOS Integration 插件主类。"""

    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.context = context
        self.config = ConfigManager(config or {})
        self.data_dir = str(StarTools.get_data_dir())

        # 运行时状态
        self._client: EverOSClient | None = None
        self._tools_registered = False
        self._healthy = False
        self._standalone_server: StandaloneServer | None = None

        # 注册 Web API
        self._register_web_apis()

        # 异步启动初始化
        self._bg_task = asyncio.create_task(self._initialize())

    # ─── Web API 路由 ──────────────────────────────────────────────

    def _register_web_apis(self) -> None:
        """注册 Plugin Page 后端 API。"""
        try:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/status",
                self.api_status,
                ["GET"],
                "EverOS 服务状态与统计",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/memories",
                self.api_memories,
                ["GET"],
                "获取 EverOS 记忆列表",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/test-memorize",
                self.api_test_memorize,
                ["POST"],
                "测试记忆写入 EverOS",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/memorize",
                self.api_memorize,
                ["POST"],
                "写入单条记忆到 EverOS",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/memories-by-type",
                self.api_memories_by_type,
                ["POST"],
                "按类型获取记忆",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/search",
                self.api_search,
                ["POST"],
                "语义检索记忆",
            )
            logger.info("📊 EverOS Web API 已注册（全功能）")
        except Exception as e:
            logger.warning(f"Web API 注册失败: {e}")

    async def api_status(self):
        """GET /api/plug/everos_integration/status"""
        if self._client is None:
            return jsonify({"healthy": False, "error": "client not initialized"})

        healthy = await self._client.is_healthy()
        stats = {}
        latency = None
        if healthy:
            try:
                t0 = time.monotonic()
                stats = await self._client.stats()
                latency = int((time.monotonic() - t0) * 1000)
            except Exception as e:
                stats = {"error": str(e)}

        return jsonify({
            "healthy": healthy,
            "latency": latency,
            "base_url": self.config.everos_base_url,
            "app_id": self.config.app_id,
            "project_id": self.config.project_id,
            "stats": stats,
        })

    async def api_memories(self):
        """GET /api/plug/everos_integration/memories

        获取最近记忆（从所有类型中取最新 10 条）。
        """
        if self._client is None:
            return jsonify({"ok": False, "error": "client not initialized", "data": {"items": []}})

        try:
            all_items = []
            for mtype in ("episode", "atomic_fact", "agent_case", "agent_skill"):
                try:
                    result = await self._client.memory_get(
                        memory_type=mtype,
                        limit=5,
                        offset=0,
                    )
                    if isinstance(result, dict):
                        data = result.get("data", result)
                        if isinstance(data, dict):
                            items = data.get("items") or data.get("memories") or data.get("results") or []
                            for item in items:
                                if isinstance(item, dict):
                                    item["memory_type"] = item.get("memory_type") or mtype
                                    all_items.append(item)
                except Exception:
                    continue

            # 按时间倒序，取前 10
            def _sort_key(item):
                ts = item.get("timestamp") or item.get("created_at") or 0
                if isinstance(ts, str):
                    try:
                        from datetime import datetime
                        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        return 0
                return ts

            if all_items:
                all_items.sort(key=_sort_key, reverse=True)
                all_items = all_items[:10]

            return jsonify({"ok": True, "data": {"items": all_items}})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "data": {"items": []}})

    async def api_test_memorize(self):
        """POST /api/plug/everos_integration/test-memorize"""
        if self._client is None:
            return jsonify({"ok": False, "error": "client not initialized"})

        try:
            body = await request.get_json()
        except Exception:
            body = {}

        content = body.get("content", "AstrBot EverOS Integration 测试消息")
        user_id = body.get("user_id", "test")

        try:
            ts = int(time.time() * 1000)
            await self._client.memory_add(
                session_id=f"webui-test-{ts}",
                messages=[{
                    "sender_id": user_id,
                    "role": "user",
                    "timestamp": ts,
                    "content": content,
                }],
                app_id=self.config.app_id,
                project_id=self.config.project_id,
            )
            await self._client.memory_flush(
                session_id=f"webui-test-{ts}",
                app_id=self.config.app_id,
                project_id=self.config.project_id,
            )
            return jsonify({"ok": True, "message": f"已写入并提取: {content}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    async def api_memorize(self):
        """POST /api/plug/everos_integration/memorize

        简化写入接口，供 Dashboard 使用。
        """
        if self._client is None:
            return jsonify({"ok": False, "error": "client not initialized"})

        try:
            body = await request.get_json()
        except Exception:
            body = {}

        content = body.get("content", "").strip()
        if not content:
            return jsonify({"ok": False, "error": "内容为空"})

        user_id = body.get("user_id", "webui")
        ts = int(time.time() * 1000)

        try:
            await self._client.memory_add(
                session_id=f"webui-{user_id}-{ts}",
                messages=[{
                    "sender_id": user_id,
                    "role": "user",
                    "timestamp": ts,
                    "content": content,
                }],
                app_id=self.config.app_id,
                project_id=self.config.project_id,
            )
            await self._client.memory_flush(
                session_id=f"webui-{user_id}-{ts}",
                app_id=self.config.app_id,
                project_id=self.config.project_id,
            )
            return jsonify({"ok": True, "status": "ok", "message": "记忆已写入"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    async def api_memories_by_type(self):
        """POST /api/plug/everos_integration/memories-by-type

        按类型获取记忆列表。
        """
        if self._client is None:
            return jsonify({"ok": False, "error": "client not initialized", "data": {"items": []}})

        try:
            body = await request.get_json()
        except Exception:
            body = {}

        memory_type = body.get("memory_type", "episode")
        limit = min(body.get("limit", 30), 100)

        try:
            result = await self._client.memory_get(
                memory_type=memory_type,
                limit=limit,
                offset=0,
            )
            items = []
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    items = data.get("items") or data.get("memories") or data.get("results") or []
            return jsonify({"ok": True, "data": {"items": items}})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "data": {"items": []}})

    async def api_search(self):
        """POST /api/plug/everos_integration/search

        语义检索记忆。
        """
        if self._client is None:
            return jsonify({"ok": False, "error": "client not initialized", "results": []})

        try:
            body = await request.get_json()
        except Exception:
            body = {}

        query = body.get("query", "").strip()
        if not query:
            return jsonify({"ok": False, "error": "查询为空", "results": []})

        top_k = min(body.get("top_k", 10), 50)

        try:
            result = await self._client.memory_search(
                query=query,
                user_id="webui",
                app_id=self.config.app_id,
                project_id=self.config.project_id,
                top_k=top_k,
            )
            items = []
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    items = data.get("items") or data.get("results") or []
            return jsonify({"ok": True, "data": {"items": items}})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "results": []})

    # ─── 初始化 ────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        """异步初始化：连接 EverOS + 注册工具。"""
        try:
            self._client = EverOSClient(
                base_url=self.config.everos_base_url,
            )
            self._healthy = await self._client.is_healthy()

            if self._healthy:
                logger.info(f"✅ EverOS 连接成功: {self.config.everos_base_url}")
            else:
                logger.warning(
                    f"⚠️ EverOS 连接失败: {self.config.everos_base_url}，"
                    f"插件以降级模式运行"
                )

            if self.config.enable_tools and self._healthy:
                self._register_tools()

        except Exception as e:
            logger.error(f"EverOS Integration 初始化失败: {e}", exc_info=True)

        # 启动独立 WebUI 服务器（下载即用，访问 http://IP:18766）
        try:
            self._standalone_server = StandaloneServer(self)
            asyncio.create_task(self._standalone_server.start())
        except Exception as e:
            logger.warning(f"[EverOS] 独立 WebUI 启动失败: {e}（不影响插件主体功能）")

    def _register_tools(self) -> None:
        """注册 LLM 工具。"""
        if self._tools_registered or self._client is None:
            return

        tools = [
            EverOSMemorizeTool(self._client, self.config),
            EverOSRecallTool(self._client, self.config),
        ]
        try:
            self.context.add_llm_tools(*tools)
            self._tools_registered = True
            logger.info("🔧 LLM 工具已注册: everos_memorize, everos_recall")
        except Exception as e:
            logger.error(f"LLM 工具注册失败: {e}", exc_info=True)

    # ─── 命令 ──────────────────────────────────────────────────────

    @filter.command("everos")
    async def cmd_everos(self, event: AstrMessageEvent) -> None:
        """/everos — 查看 EverOS 连接状态。"""
        if self._healthy:
            yield event.plain_result(
                f"🧠 **EverOS Integration** v1.0.0\n"
                f"✅ 服务在线: {self.config.everos_base_url}\n"
                f"📱 App: `{self.config.app_id}`\n"
                f"📦 Project: `{self.config.project_id}`\n"
                f"🔧 LLM 工具: {'已注册' if self._tools_registered else '未注册'}"
            )
        else:
            yield event.plain_result(
                f"🧠 **EverOS Integration** v1.0.0\n"
                f"❌ 服务离线: {self.config.everos_base_url}\n"
                f"\n请确认 EverOS 容器是否正在运行。"
            )

    # ─── 生命周期 ──────────────────────────────────────────────────

    async def terminate(self) -> None:
        """插件卸载时关闭 HTTP 客户端和独立 WebUI。"""
        if self._client:
            await self._client.close()
        if self._standalone_server:
            await self._standalone_server.stop()
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
        logger.info("EverOS Integration 已关闭")
