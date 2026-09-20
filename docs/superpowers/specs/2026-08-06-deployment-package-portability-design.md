# 跨平台部署包与安全重部署设计

日期：2026-08-06
状态：已确认，待实施

## 背景

Windows 上的 `pack.ps1` 使用 `Compress-Archive` 打包暂存目录。归档条目保留了 Windows 反斜杠，例如 `code\backend\.env`。Ubuntu 上用 `python3 -m zipfile -e` 解压时，反斜杠不是目录分隔符，条目会被创建成部署根目录下名称包含反斜杠的普通文件。

因此，正确的 `code/`、`data/`、`secrets/` 目录没有被覆盖，服务器继续运行旧代码和旧部署脚本；本次生成的错误文件也留在部署根目录。

## 目标

1. 部署包在 Windows 生成、Ubuntu 解压后具有正确的 POSIX 目录结构。
2. 打包阶段拒绝任何包含反斜杠的 ZIP 条目，禁止交付不可部署的包。
3. 远端升级使用临时解压验证和受控替换，保留上一版的 `.env`、Docker 卷、现有业务容器及可回滚代码副本。
4. 仅清理本次错误包产生的根目录反斜杠命名条目，绝不删除真实 `code/`、`data/`、`secrets/`。
5. 新版部署恢复固定的 `3100/8100` 映射，不触碰 `lobster-*`、端口 82、端口 8000 或宝塔服务。

## 范围

### 包含

- 重写 `pack.ps1` 的 ZIP 写入方式，显式以 `/` 生成归档路径。
- 本地归档结构验证。
- `deploy.sh` 增加一个服务器端解压前置检查或配套升级脚本，验证临时目录的预期结构。
- 受控升级、错误条目清理、备份和回滚操作说明。

### 不包含

- 修改业务应用逻辑。
- 删除或重建 `lobster-*` 容器、宝塔 Nginx/MySQL。
- 无确认地合并服务器端新产生的数据到本地 dump；数据库仍以本次打包的本地 dump 为准。

## 设计

### 1. 生成可移植 ZIP

`pack.ps1` 保留现有四阶段数据收集：本地 PostgreSQL dump、`prod.env`、`backend/frontend/deploy` 代码、`backend/var` 文件库。

打包改用 .NET `System.IO.Compression.ZipArchive`。每个文件计算相对于 staging 根目录的路径，并将 `\` 替换为 `/` 后写入 ZIP。目录条目不依赖 Windows 路径语义。

打包完成后重新打开 ZIP，并执行以下硬校验：

- 条目数大于 0。
- 任一条目含 `\` 时立即失败并删除 ZIP。
- 必须存在 `code/deploy/deploy.sh`、`code/backend/requirements.txt`、`code/frontend/package.json`、`data/rbac.dump`、`secrets/prod.env`。
- 输出上述关键条目和 ZIP 大小，作为上传前证据。

### 2. 服务器端临时验收

主包不再直接解压到 `/opt/agent_loop`。操作顺序固定为：

1. 上传 ZIP 至 `/opt/agent_loop`。
2. 解压到 `/opt/agent_loop/.incoming-<时间戳>`。
3. 验证其为真实目录且关键文件存在：`code/deploy/deploy.sh`、`code/backend`、`code/frontend`、`data/rbac.dump`、`secrets/prod.env`。
4. 查找临时目录中名称包含反斜杠的条目；找到即终止，保留当前部署不变。
5. 通过后才执行受控替换。

### 3. 数据、配置与代码替换边界

升级前在 `/opt/agent_loop/backups/<时间戳>/` 保存：

- 当前 `code/`，用于代码回滚。
- `code/deploy/.env`，用于保留服务器已生成的数据库密码及密钥。
- 当前 `data/`，用于保留上一版传输的数据文件。
- PostgreSQL 当前 `rbac` 数据库的 `pg_dump -Fc` 备份，防止远端产生的数据被新本地 dump 覆盖。

替换时只替换 `code/`、`data/`、`secrets/`。恢复当前 `.env` 到新 `code/deploy/.env`，以确保部署脚本复用已初始化的数据库密码。PostgreSQL、Redis、文件库 Docker 卷均不删除。

数据库恢复继续使用部署包的 `data/rbac.dump`。因此服务器端新增数据会被覆盖；升级脚本先生成数据库备份，以支持人工恢复或回滚。

### 4. 错误反斜杠条目清理

先执行只读清单：在 `/opt/agent_loop` 的第一层查找名称含 `\` 的文件。确认列表仅包含错误解压产生的文件后，按精确名称删除。

禁止使用通配范围删除 `code`、`data`、`secrets`，也禁止递归清空部署根目录。清理发生在临时目录验证成功、旧目录备份完成之后。

### 5. 固定端口与恢复

已有新版 `deploy.sh` 必须随正确目录结构部署，并负责：

- 复用已有 `.env` 的密钥和 PostgreSQL 密码。
- 识别自身容器端口，不把 `agent-*` 占用的旧端口错误判为外部冲突。
- 将本次升级的端口显式固定为 `FE_PORT=3100`、`BE_PORT=8100`；若被非 agent 服务占用则终止并报告，不允许静默漂移到 3101/8101。
- 恢复前停止并验证 agent 应用容器已停，清理 `rbac` 活动连接，再删除、建库、导入。
- 最后重建并启动 agent 容器。

升级期间 agent 服务短暂离线；`lobster-*` 容器不停止、不改网络、不改端口、不访问其卷。

## 验证与验收

### 本地

1. 运行 `pack.ps1`。
2. 用 ZIP API 检查：全部条目含 `/` 或无分隔符，反斜杠条目为 0。
3. 解压至本地临时目录，验证五个关键路径均为实际目录/文件。
4. 用一个故意构造的反斜杠条目 ZIP 验证校验会失败。

### 远端

1. 临时解压检查通过，确认根目录未新增反斜杠命名条目。
2. 完成备份后受控替换，运行部署。
3. `docker port agent-frontend` 显示 `3100->3000`；`agent-backend` 显示 `8100->8000`。
4. 六个 agent 容器运行，postgres/backend 健康检查通过。
5. 访问 `http://115.29.187.169:3100` 并验证登录。
6. `docker ps` 确认所有 `lobster-*` 容器仍为运行状态。

## 回滚

部署失败时停止 agent 容器，将备份的 `code/`、`data/`、`.env` 恢复，使用备份数据库 dump 恢复 `rbac`，再以备份代码运行部署脚本。该回滚只影响 agent 资源，不触及 `lobster-*`。
