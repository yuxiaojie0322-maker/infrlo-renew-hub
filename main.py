import os
import time
import uuid
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("renew_hub")

from tasks.task_manager import registry
from tasks.demo_ping import run_ping_task
from tasks.duckdns import run_duckdns_renew

START_TIME = time.time()
scheduler = AsyncIOScheduler()
registry.set_scheduler(scheduler)

# 默认安全密码
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin888")
COOKIE_AUTH_KEY = "renew_hub_session"
AUTH_TOKEN_VALUE = "auth_valid_token_30d"

# 注册默认示例任务
registry.register(
    task_id="probe_ping",
    name="探针与心跳保活",
    description="定时探测指定外部 URL 并自保活",
    interval_type="minutes",
    interval_value=10,
    func=run_ping_task
)

registry.register(
    task_id="duckdns_renew",
    name="DuckDNS 域名保活",
    description="防止免费动态二级域名因 30 天未更新被释放",
    interval_type="hours",
    interval_value=12,
    func=run_duckdns_renew
)

# 调度器触发包装
async def scheduled_runner(task_id: str):
    logger.info(f"⏰ 定时触发任务: {task_id}")
    await registry.execute_task(task_id)

def schedule_single_task(task_id: str, interval_type: str, interval_value: Any):
    try:
        job_id = f"job_{task_id}"
        if interval_type == "minutes":
            mins = int(interval_value)
            scheduler.add_job(scheduled_runner, IntervalTrigger(minutes=mins), args=[task_id], id=job_id, replace_existing=True)
        elif interval_type == "hours":
            hrs = int(interval_value)
            scheduler.add_job(scheduled_runner, IntervalTrigger(hours=hrs), args=[task_id], id=job_id, replace_existing=True)
        elif interval_type == "daily":
            parts = str(interval_value).split(":")
            h = int(parts[0]) if len(parts) > 0 else 8
            m = int(parts[1]) if len(parts) > 1 else 0
            scheduler.add_job(scheduled_runner, CronTrigger(hour=h, minute=m), args=[task_id], id=job_id, replace_existing=True)
    except Exception as e:
        logger.error(f"调度任务 {task_id} 挂载失败: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 尝试从本地持久化加载用户之前保存的任务
    registry.load_from_file()
    
    # 2. 挂载所有任务到调度器
    for t_id, task in registry.tasks.items():
        schedule_single_task(t_id, task["interval_type"], task["interval_value"])
        
    scheduler.start()
    logger.info("🚀 APScheduler 异步调度引擎已启动，所有动态与静态任务已全部就绪！")
    yield
    scheduler.shutdown()
    logger.info("🛑 APScheduler 已停止")

app = FastAPI(title="Infrlo Auto-Renew Hub", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# --- 登录与身份鉴权逻辑 ---
def check_authenticated(request: Request) -> bool:
    cookie_val = request.cookies.get(COOKIE_AUTH_KEY)
    return cookie_val == AUTH_TOKEN_VALUE

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if check_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(key=COOKIE_AUTH_KEY, value=AUTH_TOKEN_VALUE, max_age=86400 * 30, httponly=True)
        return resp
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "密码不正确，请重新输入"})

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_AUTH_KEY)
    return resp

# --- 主界面 ---
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """状态可视化仪表盘"""
    if not check_authenticated(request):
        return RedirectResponse("/login", status_code=302)
        
    try:
        uptime_sec = int(time.time() - START_TIME)
        hours = uptime_sec // 3600
        minutes = (uptime_sec % 3600) // 60
        seconds = uptime_sec % 60
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        
        tg_ready = bool(os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID"))
        summary = registry.get_summary()
        
        context_data = {
            "request": request,
            "summary": summary,
            "uptime_str": uptime_str,
            "tg_ready": tg_ready
        }
        return templates.TemplateResponse(request=request, name="index.html", context=context_data)
    except Exception as e:
        logger.error(f"渲染页面异常: {e}", exc_info=True)
        return HTMLResponse(f"<h3>控制台渲染异常</h3><pre>{str(e)}</pre>", status_code=500)

# --- 免密健康检查（用于平台探针） ---
@app.get("/health")
async def health_check():
    """Infrlo 平台探针接口：返回 200 OK 防止容器判定离线"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": int(time.time() - START_TIME)
    }

# --- 任务 API 增删改查 ---
@app.post("/api/tasks")
async def create_task(request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    data = await request.json()
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    name = data.get("name", "未命名任务")
    interval_type = data.get("interval_type", "hours")
    interval_value = data.get("interval_value", 12)
    http_config = data.get("http_config", {})

    registry.register(
        task_id=task_id,
        name=name,
        description=http_config.get("url", ""),
        interval_type=interval_type,
        interval_value=interval_value,
        http_config=http_config
    )
    schedule_single_task(task_id, interval_type, interval_value)
    return {"status": "ok", "task_id": task_id}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    data = await request.json()
    if task_id not in registry.tasks:
        return JSONResponse({"status": "error", "message": "任务不存在"}, status_code=404)
        
    task = registry.tasks[task_id]
    task["name"] = data.get("name", task["name"])
    task["interval_type"] = data.get("interval_type", task["interval_type"])
    task["interval_value"] = data.get("interval_value", task["interval_value"])
    task["http_config"] = data.get("http_config", task.get("http_config"))
    task["description"] = task["http_config"].get("url", "")
    
    interval_type = task["interval_type"]
    interval_value = task["interval_value"]
    if interval_type == "minutes":
        task["interval_desc"] = f"每 {interval_value} 分钟"
    elif interval_type == "hours":
        task["interval_desc"] = f"每 {interval_value} 小时"
    elif interval_type == "daily":
        task["interval_desc"] = f"每天 {interval_value}"

    registry.save_to_file()
    schedule_single_task(task_id, interval_type, interval_value)
    return {"status": "ok"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    if registry.delete_task(task_id):
        try:
            scheduler.remove_job(f"job_{task_id}")
        except Exception:
            pass
        return {"status": "ok"}
    return JSONResponse({"status": "error", "message": "任务不存在"}, status_code=404)

@app.post("/api/trigger/{task_id}")
async def trigger_task(task_id: str, request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    res = await registry.execute_task(task_id)
    return JSONResponse(content=res)

@app.get("/api/export")
async def export_tasks(request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    return registry.tasks

@app.post("/api/import")
async def import_tasks(request: Request):
    if not check_authenticated(request):
        return JSONResponse({"status": "error", "message": "未登录"}, status_code=401)
    data = await request.json()
    if isinstance(data, dict):
        for k, v in data.items():
            registry.tasks[k] = v
            schedule_single_task(k, v.get("interval_type", "hours"), v.get("interval_value", 12))
        registry.save_to_file()
        return {"status": "ok"}
    return JSONResponse({"status": "error", "message": "无效配置格式"}, status_code=400)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 正在启动服务，监听端口: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
