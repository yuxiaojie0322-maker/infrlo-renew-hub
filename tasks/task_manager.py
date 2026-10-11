import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Callable

logger = logging.getLogger("renew_hub")

class TaskRegistry:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []

    def register(self, task_id: str, name: str, description: str, interval_desc: str, func: Callable):
        self.tasks[task_id] = {
            "id": task_id,
            "name": name,
            "description": description,
            "interval_desc": interval_desc,
            "func": func,
            "last_run": None,
            "last_status": "PENDING", # PENDING, SUCCESS, FAILED, RUNNING
            "last_message": "尚未执行",
            "last_duration": 0.0,
            "total_runs": 0,
            "total_success": 0,
            "total_failed": 0
        }

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
            func = task["func"]
            success, message = await func()
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
                
            task["last_message"] = message
            self.append_log(task_id, task["last_status"], message, duration)
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
            return {"status": "FAILED", "message": str(e), "duration": duration}

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_tasks": len(self.tasks),
            "tasks": list(self.tasks.values()),
            "recent_logs": self.logs[:15]
        }

registry = TaskRegistry()
