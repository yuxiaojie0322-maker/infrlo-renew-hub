import os
import uvicorn
from main import app, logger

if __name__ == "__main__":
    # Infrlo 分配并期望的端口是 5000
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 正在通过 app.py 启动服务，监听端口: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
