import os
import uvicorn
from main import app, logger

if __name__ == "__main__":
    # 优先读取 Infrlo 注入的 PORT 环境变量，默认 8080
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🌐 正在通过 app.py 启动服务，监听端口: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
