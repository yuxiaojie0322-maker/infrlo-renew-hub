import os
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# 加载本地环境变量
load_dotenv()

# 日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("renew_hub")

from tasks.task_manager import registry
from tasks.demo_ping import run_ping_task
from tasks.duckdns import run_duckdns_renew

START_TIME = time.time()
scheduler = AsyncIOScheduler()

# 注册任务定义
registry.register(
    task_id="probe_ping",
    name="探针与心跳保活",
    description="定时探测指定外部 URL 并自保活",
    interval_desc="每 10 分钟",
    func=run_ping_task
)

registry.register(
    task_id="duckdns_renew",
    name="DuckDNS 域名保活",
    description="防止免费动态二级域名因 30 天未更新被释放",
    interval_desc="每 12 小时",
    func=run_duckdns_renew
)

# 调度器触发包装
async def scheduled_runner(task_id: str):
    logger.info(f"⏰ 定时触发任务: {task_id}")
    await registry.execute_task(task_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动调度器并挂载任务
    scheduler.add_job(scheduled_runner, IntervalTrigger(minutes=10), args=["probe_ping"], id="job_probe_ping", replace_existing=True)
    scheduler.add_job(scheduled_runner, IntervalTrigger(hours=12), args=["duckdns_renew"], id="job_duckdns_renew", replace_existing=True)
    scheduler.start()
    logger.info("🚀 APScheduler 异步调度引擎已启动，任务就绪！")
    yield
    scheduler.shutdown()
    logger.info("🛑 APScheduler 已停止")

app = FastAPI(title="Infrlo Auto-Renew Hub", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """状态可视化仪表盘"""
    uptime_sec = int(time.time() - START_TIME)
    hours = uptime_sec // 3600
    minutes = (uptime_sec % 3600) // 60
    seconds = uptime_sec % 60
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    tg_ready = bool(os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID"))
    summary = registry.get_summary()
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary": summary,
            "uptime_str": uptime_str,
            "tg_ready": tg_ready
        }
    )

@app.get("/health")
async def health_check():
    """Infrlo 平台探针接口：返回 200 OK 防止容器判定离线"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": int(time.time() - START_TIME)
    }

@app.post("/api/trigger/{task_id}")
async def trigger_task(task_id: str):
    """手动立即触发测试接口"""
    logger.info(f"👆 收到手动触发请求: {task_id}")
    res = await registry.execute_task(task_id)
    return JSONResponse(content=res)

if __name__ == "__main__":
    import uvicorn
    # Infrlo 会自动在容器中注入 PORT 环境变量
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🌐 正在启动服务，监听端口: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
