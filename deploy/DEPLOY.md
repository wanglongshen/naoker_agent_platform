# 一键部署手册（傻瓜式）

> 推荐方式 A（纯宝塔浏览器操作，最简单）；方式 B（Xftp + Xshell）备选。

## 方式 A：宝塔面板操作（推荐，无需 Xftp/Xshell）

### 你需要准备
- 宝塔面板登录地址（安装宝塔时显示的 `http://115.29.187.169:8888/xxxxx`）
- 本地已打包的 `C:\agent-deploy\agent-deploy.zip`

### A1. 本地打包（Windows 电脑上做一次）
1. 打开 PowerShell，执行：
   ```
   cd C:\01_agent_loop_pro
   powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
   ```
2. 打包完成后确认 `C:\agent-deploy\agent-deploy.zip` 存在

### A2. 上传（宝塔「文件」）
1. 浏览器登录宝塔面板
2. 左侧菜单点「文件」→ 地址栏进入 `/opt` →「新建」→「新建目录」→ 输入 `agent_loop` → 确认
3. 双击进入 `/opt/agent_loop` → 点「上传」→ 选择本地 `agent-deploy.zip` → 等上传完成

### A3. 解压 + 部署（宝塔「终端」，一条命令）
1. 左侧菜单点「终端」→「开始终端」（默认 root，直接可用）
2. 粘贴执行（粘贴后按回车）：
   ```
   cd /opt/agent_loop
   ```
   ```
   bash code/deploy/upgrade.sh agent-deploy.zip
   ```
3. 脚本会自动：临时解压验收结构 → 备份旧代码/数据/数据库 → 清理历史错误文件 → 替换 → 部署
4. **等待 5-15 分钟**（下载基础镜像 + 构建 + 还原数据）。每步显示 ✅/❌，最后出现「部署完成」报告：
   - 报告含前端地址（`http://115.29.187.169:3100`）和 admin 密码
   - **马上截图**——密码只显示这一次（脚本自动销毁密钥文件）

### A4. 使用
浏览器打开 `http://115.29.187.169:3100`，用 `admin` + 截图里的密码登录。
验证：历史会话可见、文件库文件可读、发一条消息看流式回复。

### A5. 以后升级（新版本打包后）
1. 本地重新运行 pack.ps1，得到新 agent-deploy.zip
2. 上传覆盖 /opt/agent_loop/agent-deploy.zip
3. 终端执行同一条命令：
   ```
   bash code/deploy/upgrade.sh agent-deploy.zip
   ```
   备份自动存到 /opt/agent_loop/backups/<时间戳>/（旧代码/数据/数据库，可回滚）

## 方式 B：Xftp + Xshell（备选）

### 第一步：本地打包（同 A1）

### 第二步：上传（Xftp）
1. Xftp 连接服务器（IP 115.29.187.169）
2. 进入 /opt 目录，新建文件夹 agent-deploy
3. 把 agent-deploy.zip 拖进 /opt/agent_loop/

### 第三步：部署（Xshell）
1. Xshell 连接服务器
2. 依次执行：
   ```
   cd /opt/agent_loop
   bash code/deploy/upgrade.sh agent-deploy.zip
   ```
3. 等待部署完成（约 5-15 分钟），看到报告后**截图保存**（admin 密码仅出现一次）

## 日常运维（宝塔「终端」或 Xshell，在 /opt/agent_loop/code/deploy 下）
| 命令 | 作用 |
|---|---|
| bash logs.sh backend | 看后端日志 |
| bash restart.sh | 重启全部服务 |
| bash backup.sh | 备份数据库+文件库（到 backups/） |
| bash status.sh | 查看容器状态与内存 |
| bash logs.sh worker | 看 worker 日志（跑任务用） |

服务器重启后：什么都不用做，全部容器自动拉起（restart: unless-stopped）。

**回滚**：部署失败时 `bash restart.sh` 无法解决，可执行：
```
cd /opt/agent_loop/backups/<最新时间戳>
cp -a code /opt/agent_loop/code && cp -a data /opt/agent_loop/data
bash /opt/agent_loop/code/deploy/deploy.sh
```

## 常见问题
| 问题 | 处理 |
|---|---|
| 端口被占用 | 端口固定为 3100/8100。若报「固定端口已被其他服务占用」：先释放该端口，或手动编辑 code/deploy/.env 的 FE_PORT/BE_PORT 后重跑（不推荐改） |
| 部署中断 | 重新执行部署命令（幂等可重跑，构建缓存自动续） |
| 登录不了 | 确认报告里的 admin 密码（只显示一次）；丢了就执行 grep INITIAL_ADMIN_PASSWORD /opt/agent_loop/code/deploy/.env |
| 任务报 deepseek_auth_error / 登录后所有功能异常 | 半成品 .env 残留占位符。新版脚本已自动检测并回退 prod.env；若仍报错：rm -f /opt/agent_loop/code/deploy/.env 后重跑部署 |
| 报「数据库密码失配」 | 旧数据库卷与新 .env 密码不一致。按脚本提示执行 down + 删卷（agent_agent-pgdata）后重跑，数据从 rbac.dump 恢复 |
| 模型读文件内容为空（"我的文件"打不开） | 旧 dump 的 storage_key 是 Windows 反斜杠路径。新版脚本还原后自动规范化；手动修复：docker exec agent-postgres psql -U agent -d rbac -c "UPDATE file_objects SET storage_key = replace(storage_key, chr(92), '/') WHERE strpos(storage_key, chr(92)) > 0;" |
| 平台搜索（小红书/抖音）报 InvalidTag / 平台工具崩溃 | 平台 cookie 用旧密钥加密，远端 FEISHU_TOKEN_ENCRYPTION_KEY 是新随机值 → 解密失败。修复：sed -i 's/^FEISHU_TOKEN_ENCRYPTION_KEY=.*/FEISHU_TOKEN_ENCRYPTION_KEY=/' /opt/agent_loop/code/deploy/.env && docker restart agent-backend agent-worker（回退用 JWT_SECRET 解密）；仍失败则重新走平台登录授权（扫码）生成新 cookie |
| 报 set: pipefail: invalid option name | 脚本行尾是 CRLF（Xftp 自动转换）。修复：find /opt/agent_loop/code -name "*.sh" -exec sed -i 's/\r$//' {} + ；以后用 Xftp 传脚本时把传输模式切到 Binary（二进制） |
| 部署中途"突然断了"（构建被杀） | 4G 内存机器构建期 OOM。新版脚本已内置：构建前自动停旧容器 + 串行构建；仍断则配置 Docker 镜像加速（见步骤 1 提示） |
| 服务挂了 | bash restart.sh |
| 宝塔终端粘贴没反应 | 先点一下终端窗口再粘贴 |
| 忘记截图 | grep INITIAL_ADMIN_PASSWORD /opt/agent_loop/code/deploy/.env |
