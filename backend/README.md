# backend

FastAPI 服务（API / agent_worker / web_renderer 三进程）。

## 部署注意

- 扫码登录（平台登录中心）依赖 **patchright** 的浏览器二进制：
  - 安装：`pip install patchright`
  - 安装浏览器（首次部署必须执行）：`patchright install chromium`
  - Linux 服务器如需系统依赖（libnss3 等），参考 Playwright 官方依赖清单：
    `python -m patchright install-deps chromium`
- **真实窗口模式（必须）**：反爬实测确认 headless 模式会被抖音/小红书拦截，
  因此浏览器以 `headless=False` 启动（`.env` 可配 `WEB_RENDERER_HEADLESS`/`WEB_RENDERER_CHANNEL`）：
  - Windows 开发机：直接弹窗（channel 默认 `msedge`）
  - Linux 生产：用 xvfb 虚拟显示承载，启动命令：
    `xvfb-run -a python -m app.workers.web_renderer`
    （Debian/Ubuntu 安装：`apt install xvfb`；RHEL 系：`dnf install xorg-x11-server-Xvfb`）
- 登录态相关环境变量见 `.env`（web_renderer_url 等）。
