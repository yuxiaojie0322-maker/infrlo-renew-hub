import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx
from notifier import send_tg_notification

logger = logging.getLogger("renew_hub")
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tasks.json")

class TaskRegistry:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.scheduler = None

    def set_scheduler(self, sched):
        self.scheduler = sched

    def load_from_file(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for t in saved:
                    t_id = t.get("id")
                    if t_id and t_id not in self.tasks:
                        self.tasks[t_id] = t
                        # 重新载入时重置状态
                        self.tasks[t_id]["last_status"] = t.get("last_status", "PENDING")
                        self.tasks[t_id]["last_message"] = t.get("last_message", "已加载")
        except Exception as e:
            logger.error(f"加载任务数据失败: {e}")

    def save_to_file(self):
        try:
            to_save = []
            for t in self.tasks.values():
                item = dict(t)
                # 不存储不可序列化字段
                item.pop("func", None)
                to_save.append(item)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存任务数据失败: {e}")

    def register(self, task_id: str, name: str, description: str, interval_type: str, interval_value: Any, func=None, http_config=None):
        interval_desc = f"{interval_type} {interval_value}"
        if interval_type == "minutes":
            interval_desc = f"每 {interval_value} 分钟"
        elif interval_type == "hours":
            interval_desc = f"每 {interval_value} 小时"
        elif interval_type == "daily":
            interval_desc = f"每天 {interval_value}"

        self.tasks[task_id] = {
            "id": task_id,
            "name": name,
            "description": description or "",
            "interval_type": interval_type,
            "interval_value": interval_value,
            "interval_desc": interval_desc,
            "func": func,
            "http_config": http_config, # {method, url, headers, cookie, body, success_keyword}
            "last_run": None,
            "last_status": "PENDING",
            "last_message": "尚未执行",
            "last_duration": 0.0,
            "total_runs": 0,
            "total_success": 0,
            "total_failed": 0
        }
        self.save_to_file()

    def append_log(self, task_id: str, status: str, message: str, duration: float):
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "task_id": task_id,
            "task_name": self.tasks.get(task_id, {}).get("name", task_id),
            "status": status,
            "message": message,
            "duration": f"{duration:.2f}s"
        }
        self.logs.insert(0, entry)
        if len(self.logs) > 60:
            self.logs.pop()

    async def execute_task(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self.tasks:
            return {"status": "ERROR", "message": "任务不存在"}
            
        task = self.tasks[task_id]
        task["last_status"] = "RUNNING"
        start_time = time.time()
        
        try:
            # 1. 如果是代码注册的任务
            if task.get("func"):
                success, message = await task["func"]()
            # 2. 如果是网页动态添加的 HTTP 任务
            elif task.get("http_config"):
                success, message = await self._run_http_task(task)
            else:
                success, message = False, "任务未定义执行器"

            duration = time.time() - start_time
            task["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            task["last_duration"] = duration
            task["total_runs"] += 1
            
            if success:
                task["last_status"] = "SUCCESS"
                task["total_success"] += 1
            else:
                task["last_status"] = "FAILED"
                task["total_failed"] += 1
                await send_tg_notification(f"⚠️ [任务失败告警] {task['name']}\n详情: {message}")
                
            task["last_message"] = message
            self.append_log(task_id, task["last_status"], message, duration)
            self.save_to_file()
            return {"status": task["last_status"], "message": message, "duration": duration}
        except Exception as e:
            duration = time.time() - start_time
            task["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            task["last_status"] = "FAILED"
            task["last_duration"] = duration
            task["total_runs"] += 1
            task["total_failed"] += 1
            task["last_message"] = f"异常错误: {str(e)}"
            self.append_log(task_id, "FAILED", f"异常: {str(e)}", duration)
            await send_tg_notification(f"❌ [任务异常] {task.get('name', task_id)}\n错误: {str(e)}")
            self.save_to_file()
            return {"status": "FAILED", "message": str(e), "duration": duration}

    async def _run_http_task(self, task: Dict[str, Any]):
        cfg = task.get("http_config", {})
        method = cfg.get("method", "GET").upper()
        url = cfg.get("url", "").strip()
        headers_str = cfg.get("headers", "").strip()
        cookie_str = cfg.get("cookie", "").strip()
        body_str = cfg.get("body", "").strip()
        success_kw = cfg.get("success_keyword", "").strip()

        if not url:
            return False, "目标 URL 不能为空"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if headers_str:
            for line in headers_str.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
        if cookie_str:
            headers["Cookie"] = cookie_str

        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                # 尝试解析为 JSON，否则作为文本
                content_type = headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        resp = await client.post(url, headers=headers, json=json.loads(body_str) if body_str else {})
                    except Exception:
                        resp = await client.post(url, headers=headers, content=body_str)
                else:
                    resp = await client.post(url, headers=headers, content=body_str)
            else:
                resp = await client.request(method, url, headers=headers, content=body_str)

            code = resp.status_code
            text = resp.text[:400]
            
            if code >= 400:
                return False, f"HTTP {code} 响应错误: {text[:150]}"

            if success_kw:
                if success_kw in text:
                    return True, f"HTTP {code} (匹配到成功关键词 '{success_kw}')"
                else:
                    return False, f"HTTP {code} 但未找到关键词 '{success_kw}', 返回: {text[:100]}"

            return True, f"HTTP {code} 请求成功, 响应: {text[:100]}"

    def delete_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.save_to_file()
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_tasks": len(self.tasks),
            "tasks": list(self.tasks.values()),
            "recent_logs": self.logs[:15]
        }

registry = TaskRegistry()
