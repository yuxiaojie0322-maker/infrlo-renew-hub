import os
import httpx
from notifier import send_tg_notification

async def run_duckdns_renew():
    """DuckDNS 动态域名定期心跳与续期"""
    domain = os.environ.get("DUCKDNS_DOMAIN", "")
    token = os.environ.get("DUCKDNS_TOKEN", "")
    
    if not domain or not token:
        return True, "未配置 DUCKDNS 凭证，任务处于待命状态"
        
    url = f"https://www.duckdns.org/update?domains={domain}&token={token}&ip="
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            text = resp.text.strip()
            if text == "OK":
                return True, f"DuckDNS 域名 {domain} 心跳刷新成功 (OK)"
            else:
                msg = f"DuckDNS 刷新返回异常: {text}"
                await send_tg_notification(f"❌ [DuckDNS 续期异常] {domain}: {text}")
                return False, msg
    except Exception as e:
        msg = f"DuckDNS 请求失败: {str(e)}"
        await send_tg_notification(f"❌ [DuckDNS 网络错误] {domain}: {str(e)}")
        return False, msg
