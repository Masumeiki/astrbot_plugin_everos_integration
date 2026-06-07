"""
EverOS 独立 WebUI 服务器。

插件加载时自动启动，用户访问配置的端口即可看到 Dashboard。
参考主动消息插件的 WebAdminServer 实现。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    import httpx

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning(
        "[EverOS] FastAPI 未安装，独立 WebUI 不可用。请安装: pip install fastapi uvicorn httpx"
    )


class StandaloneServer:
    """EverOS 独立 WebUI 服务器。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.config = plugin.config
        self.app: FastAPI | None = None
        self.server = None
        self.server_task: asyncio.Task | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._running = False

        if FASTAPI_AVAILABLE:
            try:
                self._setup_app()
            except Exception as e:
                self.app = None
                logger.error(f"[EverOS] 独立 WebUI 初始化失败: {e}，已自动禁用")

    def _get_everos_url(self) -> str:
        """从插件配置获取 EverOS 后端地址。"""
        return self.config.get("everos_base_url", "http://127.0.0.1:8765")

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0, verify=False)
        return self._http_client

    def _setup_app(self) -> None:
        self.app = FastAPI(title="EverOS Dashboard (Standalone)")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # 静态文件（挂载到 /static 下，避免和 API 路由冲突）
        pages_dir = Path(__file__).resolve().parent.parent / "pages" / "everos-dashboard"
        self._pages_dir = pages_dir
        if pages_dir.exists():
            self.app.mount(
                "/static",
                StaticFiles(directory=str(pages_dir)),
                name="everos-dashboard",
            )
        else:
            logger.warning(f"[EverOS] Dashboard 静态目录不存在: {pages_dir}")

        self._register_routes()

    def _register_routes(self) -> None:
        if not self.app:
            return

        # ─── ⚠️ API 路由必须优先注册，避免被 catch-all 拦截 ────

        self._register_api_routes()

        # ─── 首页 ────────────────────────────────────────────────

        @self.app.get("/")
        async def index():
            """返回 Dashboard HTML。"""
            html_path = self._pages_dir / "index.html"
            if not html_path.exists():
                return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
            html = html_path.read_text(encoding="utf-8")
            return HTMLResponse(html)

        @self.app.get("/{filename:path}")
        async def serve_static(filename: str):
            """提供 style.css / app.js 等根路径静态文件请求。"""
            file_path = self._pages_dir / filename
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return HTMLResponse(status_code=404)

    def _register_api_routes(self) -> None:
        """注册 API 路由（必须在 catch-all 之前注册）。"""
        if not self.app:
            return

        @self.app.get("/api/everos/status")
        async def api_status():
            """聚合健康检查 + 统计。"""
            client = self._get_client()
            base_url = self._get_everos_url()
            try:
                health = await client.get(f"{base_url}/health")
                health.raise_for_status()
                health_data = health.json()
                ok = health_data.get("status") == "ok"

                stats = {}
                for mtype in ("episode", "atomic_fact", "agent_case", "agent_skill"):
                    try:
                        r = await client.post(
                            f"{base_url}/api/v1/memory/get",
                            json={"memory_type": mtype, "user_id": "baizhi"},
                        )
                        data = r.json()
                        items = (data.get("data", {}).get(mtype + "s", []) or
                                data.get("data", {}).get("episodes", []) or
                                data.get(mtype + "s", []))
                        stats[mtype] = len(items) if mtype != "episode" else data.get("data", {}).get("total_count", len(items))
                    except Exception:
                        stats[mtype] = -1

                return {
                    "healthy": ok,
                    "base_url": base_url,
                    "latency": None,
                    "app_id": health_data.get("app_id", "everos"),
                    "project_id": health_data.get("project_id", "default"),
                    "stats": stats,
                }
            except Exception as e:
                return {"healthy": False, "error": str(e), "base_url": base_url, "stats": {}}

        @self.app.get("/api/everos/memories")
        async def api_memories():
            """获取各类型记忆。"""
            client = self._get_client()
            base_url = self._get_everos_url()
            try:
                all_items = []
                for mtype in ("episode", "atomic_fact", "agent_case", "agent_skill"):
                    try:
                        r = await client.post(
                            f"{base_url}/api/v1/memory/get",
                            json={"memory_type": mtype, "limit": 10, "offset": 0},
                        )
                        data = r.json()
                        items = data.get("data", {}).get("items", data.get("items", []))
                        for item in items:
                            if isinstance(item, dict):
                                item["memory_type"] = item.get("memory_type") or mtype
                                all_items.append(item)
                    except Exception:
                        continue
                return {"ok": True, "data": {"items": all_items}}
            except Exception as e:
                return {"ok": False, "error": str(e), "data": {"items": []}}

        @self.app.post("/api/everos/memorize")
        async def api_memorize(request: Request):
            """写入记忆。"""
            body = await request.json()
            content = body.get("content", "")
            memory_type = body.get("memory_type", "atomic_fact")
            user_id = body.get("user_id", "webui")
            client = self._get_client()
            base_url = self._get_everos_url()

            payload = {
                "session_id": f"webui_{user_id}",
                "app_id": self.config.get("app_id", "astrbot"),
                "project_id": self.config.get("project_id", "default"),
                "messages": [{
                    "sender_id": user_id,
                    "role": "user",
                    "timestamp": None,
                    "content": content,
                }],
            }
            try:
                resp = await client.post(f"{base_url}/api/v1/memory/add", json=payload)
                resp.raise_for_status()
                result = resp.json()
                await client.post(
                    f"{base_url}/api/v1/memory/flush",
                    json={
                        "session_id": f"webui_{user_id}",
                        "app_id": self.config.get("app_id", "astrbot"),
                        "project_id": self.config.get("project_id", "default"),
                    },
                )
                return {"ok": True, "status": "ok", "message": "记忆已写入", "data": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        @self.app.post("/api/everos/memories-by-type")
        async def api_memories_by_type(request: Request):
            """按类型获取记忆。"""
            body = await request.json()
            memory_type = body.get("memory_type", "episode")
            limit = body.get("limit", 20)
            client = self._get_client()
            base_url = self._get_everos_url()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/memory/get",
                    json={"memory_type": memory_type, "limit": limit, "offset": 0},
                )
                resp.raise_for_status()
                return {"ok": True, "data": resp.json()}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        @self.app.post("/api/everos/flush")
        async def api_flush(request: Request):
            """触发记忆提炼。"""
            body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
            session_id = body.get("session_id", "webui")
            client = self._get_client()
            base_url = self._get_everos_url()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/memory/flush",
                    json={
                        "session_id": session_id,
                        "app_id": self.config.get("app_id", "astrbot"),
                        "project_id": self.config.get("project_id", "default"),
                    },
                )
                resp.raise_for_status()
                return {"ok": True, "status": "ok", "message": "记忆提炼已触发"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        @self.app.post("/api/everos/search")
        async def api_search(request: Request):
            """语义检索。"""
            body = await request.json()
            query = body.get("query", "")
            top_k = body.get("top_k", 10)
            client = self._get_client()
            base_url = self._get_everos_url()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/memory/search",
                    json={
                        "query": query,
                        "user_id": "webui",
                        "app_id": self.config.get("app_id", "astrbot"),
                        "project_id": self.config.get("project_id", "default"),
                        "top_k": top_k,
                    },
                )
                resp.raise_for_status()
                return {"ok": True, "data": resp.json()}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        @self.app.get("/api/everos/server-info")
        async def api_server_info():
            """返回服务器自身信息（端口等）。"""
            port = self.config.get("standalone_webui", {}).get("port", 18766)
            return {
                "port": port,
                "mode": "standalone",
                "everos_url": self._get_everos_url(),
                "app_id": self.config.get("app_id", "astrbot"),
                "project_id": self.config.get("project_id", "default"),
            }

    async def start(self) -> None:
        if not FASTAPI_AVAILABLE:
            logger.error("[EverOS] 无法启动独立 WebUI: FastAPI 未安装")
            return

        if not self._running:
            if not self.config.get("standalone_webui_enabled", True):
                logger.info("[EverOS] 独立 WebUI 未启用")
                return

            host = self.config.get("standalone_webui_host", "0.0.0.0")
            port = int(self.config.get("standalone_webui_port", 18766))

            uv_cfg = uvicorn.Config(
                self.app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
            self.server = uvicorn.Server(uv_cfg)
            self._running = True

            async def _serve():
                try:
                    await self.server.serve()
                except Exception as e:
                    logger.error(f"[EverOS] 独立 WebUI 运行异常: {e}")
                finally:
                    self._running = False
                    if self._http_client:
                        await self._http_client.aclose()
                        self._http_client = None

            self.server_task = asyncio.create_task(_serve())
            logger.info(f"🌿 EverOS Dashboard → http://{host}:{port}")

    async def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
            self.server_task = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._running = False
        logger.info("[EverOS] 独立 WebUI 已停止")
