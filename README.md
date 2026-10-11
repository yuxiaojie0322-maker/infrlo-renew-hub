# Infrlo Auto-Renew Hub (自动续期与探针中心)

专为 **Infrlo (dash.infrlo.com)**、Render、Koyeb 等现代 PaaS 平台打造的轻量级自动续期、保活与定时任务管理系统。

---

## ✨ 核心特性

1. **零门槛部署与超低占用**：
   - 基于 **FastAPI + APScheduler** 全异步架构。
   - 内存占用仅约 **35MB**，极速构建，符合 Infrlo 免费层配额。
2. **可视化监控看板**：
   - 包含高颜值暗黑 Glassmorphism 仪表盘。
   - 实时展示各续期任务状态、下次执行倒计时、执行日志。
   - 支持网页端 **【一键立即触发测试】** 按钮。
3. **平台健康探针兼容**：
   - 内置 `/health` 端点，200 OK 保活，防止 PaaS 容器休眠或误判故障。
4. **模块化任务扩展**：
   - 在 `tasks/` 目录下新增任务文件，一句话即可完成注册和调度。
5. **Telegram 故障报警**：
   - 任务失败或 Cookie 过期时即时通过 Telegram Bot 推送报警信息。

---

## 🚀 在 Infrlo (dash.infrlo.com) 上部署步骤

### 第一步：登录 Infrlo 控制台
1. 打开 [https://dash.infrlo.com/](https://dash.infrlo.com/)。
2. 点击 **Continue with Google** 使用 Google 账号一键完成登录。

### 第二步：将本工程推送到 GitHub
将当前工程目录 `infrlo-renew-hub` 作为一个仓库上传至你的 GitHub（可以设为 Public 或 Private）。

### 第三步：在 Infrlo 创建应用
1. 在 Infrlo 控制台点击 **Deploy New App**。
2. 选择 **From GitHub Account**（或直接填入你的公开 GitHub 仓库 URL）。
3. 选择主分支（通常为 `main`）。
4. 配置构建与启动参数：
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
5. 在 **Environment Variables (环境变量)** 中填入所需变量（见下方说明）。
6. 点击 **Deploy Now**，等待 30 秒左右，构建完成即可获得分配的 HTTPS 域名！

---

## ⚙️ 环境变量说明 (Environment Variables)

可在 Infrlo 后台或本地 `.env` 文件中配置：

| 变量名 | 说明 | 示例 |
|---|---|---|
| `PORT` | 监听端口（Infrlo 平台会自动注入覆盖） | `8080` |
| `TG_BOT_TOKEN` | Telegram Bot Token（可选，用于报警） | `123456:ABC...` |
| `TG_CHAT_ID` | Telegram 接收报警的 Chat ID | `987654321` |
| `PING_URLS` | 需要定期保活的心跳网址（逗号隔开） | `https://your-app.infrlo.app/health` |
| `DUCKDNS_DOMAIN` | DuckDNS 动态域名名称（可选） | `myvps` |
| `DUCKDNS_TOKEN` | DuckDNS 鉴权 Token（可选） | `xxxxxxxx` |

---

## 🛠️ 如何添加你自己的新续期任务？

1. 在 `tasks/` 目录下新建一个 Python 文件，例如 `tasks/my_service.py`：
   ```python
   async def run_my_renew():
       # 你的续期请求逻辑
       # 返回 (是否成功: bool, 结果说明: str)
       return True, "续期成功"
   ```
2. 在 `main.py` 中注册即可：
   ```python
   registry.register(
       task_id="my_service",
       name="某主机续期",
       description="每日自动延期",
       interval_desc="每 24 小时",
       func=run_my_renew
   )
   # 挂载到调度器
   scheduler.add_job(scheduled_runner, IntervalTrigger(hours=24), args=["my_service"])
   ```
