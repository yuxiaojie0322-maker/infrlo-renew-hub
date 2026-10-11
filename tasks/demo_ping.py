import os
import httpx
from notifier import send_tg_notification

async def run_ping_task():
    """保活外部探针与自身 Web 接口任务"""
    urls_str = os.environ.get("PING_URLS", "")
    if not urls_str:
        return True, "未配置 PING_URLS，跳过外部保活测试"
        
    urls = [u.strip() for u in urls_str.split(",") if u.strip()]
    results = []
    has_error = False
    
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code < 400:
                    results.append(f"{url} -> 状态码 {resp.status_code}")
                else:
                    results.append(f"{url} -> 异常 {resp.status_code}")
                    has_error = True
            except Exception as e:
                results.append(f"{url} -> 超时/失败: {e}")
                has_error = True
                
    summary = " | ".join(results)
    if has_error:
        await send_tg_notification(f"⚠️ [探针保活报警] 部分节点请求异常:\n{summary}")
        return False, summary
    return True, f"全部探针请求正常: {summary}"
