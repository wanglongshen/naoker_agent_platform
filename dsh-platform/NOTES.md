# DSH 平台接口考古笔记（T2）

> 依据 vendored 上游 `deepseek-harness/`（@deepseek-ai/dsh 0.1.1-rc.2，只读）与外部插件样例 `dsh-deep-whale/maid-atelier/`。
> 所有源码路径相对仓库根 `deepseek-harness/`、`dsh-deep-whale/` 写；本文件位于 `dsh-platform/NOTES.md`，引用时加 `../` 前缀。
> 每节 = «结论» + «证据»（路径:行号 + 关键代码段）+ «本平台怎么用»。

---

## 1. 工具注册 API（「模型可调用工具」的确切入口）

### 结论

注册一个模型可调用工具 = 在 Cordis 函数插件 `export function apply(ctx, config)` 内：

```ts
ctx.tools.register(defineTool({ name, description, parameters, output, execute, ... }))
```

- 两层 API：
  - `defineTool(options)` —— `packages/core/tools/src/schema.ts:545`：把参数 DSL + 输出 schema 编译成 `ToolDefinition`，自动做参数校验（失败抛 `ToolArgsError`）、output 规范化、展示层软校验；
  - `ctx.tools.register(definition) -> () => void` —— `packages/core/tools/src/index.ts:1037`：注册进工具注册表（全局或 agent 作用域），返回 disposer；注册是 effect，插件卸载即注销。
- 插件形态：`export const name` + `export const inject = ['tools']` + `export function apply(ctx, config)`（函数插件命名导出，无 default export，否则 Loader 丢弃 namespace——`packages/AGENTS.md`）。
- 硬约束：`output: { schema, render, presentationMeta? }` 必须（缺则 TypeError，`index.ts:1039-1044`）；`run_code` 为保留名（`index.ts:1054`）；`execute(args, exec)` 里 `args` 已强类型、`exec.signal` 须转发、返回值必须是对应 `output.schema` 的 canonical JSON 值；抛错 ⇒ isError。

### 证据

`packages/core/tools/src/index.ts:1037`（register）：

```ts
register(definition: ToolDefinition): () => void {
  const name = definition.name
  const output = (definition as Partial<ToolDefinition>).output
  if (output === undefined || typeof output !== 'object'
    || typeof output.render !== 'function' ...) {
    throw new TypeError(`tool "${name}" must declare output { schema, render, presentationMeta? }`)
  }
  ...
  return this.layers.effect(ctx, layer => layer.tools.insert(name, definition), { label: 'tools.register()' })
}
```

`packages/core/tools/src/schema.ts:483-545`（DefineToolOptions + defineTool）：

```ts
export interface DefineToolOptions<S extends ParameterSchemaSpec, O extends ValueSchemaSpec> {
  readonly name: string
  readonly description: string
  readonly parameters: S            // 每属性 DSL → 隐式开放对象根
  readonly output: { schema: O; render(args, value): ContentBlock[]; presentationMeta? }
  readonly timeoutMs?: number
  isConcurrencySafe?(args): boolean
  execute(args: InferArgs<S>, exec: ToolRunContext): Promise<InferValue<NoInfer<O>>>
  finalizeContent?(...)
  presentCall?(...); presentResult?(...)
}
export function defineTool<const S, const O>(options: DefineToolOptions<S, O>): ToolDefinition
```

官方最小样板 `docs/cookbook/adding-a-tool.md:10-40`：

```ts
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'my-tool'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(defineTool({
    name: 'read_file', description: 'Read a file from disk.',
    parameters: { path: { type: 'string', required: true, description: 'Absolute path' } },
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    async execute(args, exec) { return readFile(args.path, { encoding: 'utf8', signal: exec.signal }) },
  }))
}
```

**脚手架样例**（可直接对照的现成工具插件）：
- 完整单文件样板：`deepseek-harness/packages/todo/tool-todo/src/index.ts`（Config 声明 + `:149` register + output/render + presentCall，约 225 行；同族最小版：`packages/interaction/tool-ask-user/src/index.ts:20`）
- 无参最短形态：`deepseek-harness/examples/headless-agent/tests/code-mode.e2e.ts:138-154`

### 本平台怎么用

server-connector 按「命名导出插件 + `defineTool` + `ctx.tools.register`」实现三个平台工具；`platformBase/userId/platformToken` 从插件 Config（schemastery `required()`）读取。

---

## 2. 外部插件包接入（package.json 必需字段 + cordis.patch.yml 写法）

### 结论

- 插件包 = «npm 包 + 一个 bundle patch 文件»。必需字段：

```json
{
  "name": "@naoker/dsh-platform-connector",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "lib/index.js",
  "exports": { ".": "./lib/index.js", "./cordis.patch.yml": "./cordis.patch.yml", "./package.json": "./package.json" },
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } },
  "peerDependencies": { "@deepseek-ai/cordis": "^4.0.1" },
  "files": [ "lib/index.js", "cordis.patch.yml" ]
}
```

  - **关键判定字段是 `dsh.bundle.patch`**（`apps/cli/src/plugin.ts:36-45` 读 `manifest.dsh?.bundle?.patch`；没有它 `dsh plugin add` 只当普通依赖装、不进 profile 层栈）。
  - `type:module` + `main`/`exports."."` = Loader 插件入口；`peerDependencies` 必含 `@deepseek-ai/cordis`（外挂插件共享安装侧唯一 cordis 实例——`packages/boot/app-boot/src/profile.ts:133-143, 223-255` healProfilesModuleFallback）。
  - 纯 server 侧插件**不需要** `dsh.client` 段、`lib/client.js`、`skin.json`（那些是浏览器/皮肤插件专用）。

- **插件自带 patch 文件**（声明把「自己」插进树的一行）：

```yaml
# <pkg>/cordis.patch.yml
- insert:
    - id: naoker-platform-connector
      name: '@naoker/dsh-platform-connector'
```

- **profile 用户层「启用一行 + 传 config」**：`$DSH_HOME/profiles/web/cordis.patch.yml`（初始模板 `[]`，`profile.ts:127-131`）。第 2 层`按 id 定向覆盖`，**整段 config 替换、不合并**（`packages/bundle/web-app/cordis.patch.yml:5-6`、`base/cordis.patch.yml:1-9`）：

```yaml
# $DSH_HOME/profiles/web/cordis.patch.yml（平台写入样例）
- id: naoker-platform-connector
  config:
    platformBase: http://127.0.0.1:8000
    userId: u-1
    platformToken: <短时平台token>
```

  - 该文件受 profile-boot 监视、热载（`apps/cli/src/profile-boot.ts:285-294` watchUserPatches：编辑即时生效，无需重启 web 进程）。
  - 动态值可用 `!!js` 表达式（仅限 plugin config / entry disabled；先例 `base/cordis.patch.yml:41` `mode: !!js process.env.DSH_TOOLS_MODE`）；平台刷新 token 直接写字面量即可。
  - 传 config 两种途径：① 插件自身 patch 行内 `config:` 字面量；② profile 用户层按 id 定向覆盖。**我们选 ②**（值随实例生成，与「插件启用」统一在一行内）。

- **安装**：`dsh plugin --profile web add <path-or-git-url>` ⇒ profile 目录内 `pnpm add` + reconcile（声明过 `dsh.bundle.patch` 才追加进 `package.json` 的 `dsh.profile.bundles`；`apps/cli/src/plugin.ts:59-91,120-157`；相对路径按调用目录锚定 `:104-112`）。
- profile 目录 = `$DSH_HOME/profiles/web/`（`app-boot/src/profile.ts:104-111`），内容：`package.json`（name=`dsh-profile-web`、dependencies、`dsh.profile.bundles`）、`cordis.patch.yml`、`pnpm-workspace.yaml`（nodeLinker: hoisted）、`cordis.yml`（空根 `[]`）。
- 加载顺序：bundle 层（按 bundles 数组序）→ profile 用户层 → `$DSH_HOME/cordis.patch.yml` → `--patch` 覆盖 → telemetry 开关（`apps/cli/src/profile-boot.ts:121-171`）。

**纯 server 侧、无 client bundle 插件的最小 package.json**（答案，骨架已建）：

```json
{
  "name": "@naoker/dsh-platform-connector",
  "version": "0.1.0",
  "type": "module",
  "private": true,
  "main": "lib/index.js",
  "exports": {
    ".": "./lib/index.js",
    "./cordis.patch.yml": "./cordis.patch.yml",
    "./package.json": "./package.json"
  },
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } },
  "peerDependencies": { "@deepseek-ai/cordis": "^4.0.1" },
  "files": ["lib/index.js", "cordis.patch.yml"]
}
```

### 证据

- 插件清单字段：`dsh-deep-whale/maid-atelier/package.json:7,14-22,28-30,38-50`（`main`、`dsh: {bundle: {patch}}`、`dsh: {client: ...}`、peerDeps cordis、files）。
- patch 行形态（外部插件先例）：`dsh-deep-whale/maid-atelier/cordis.patch.yml:5-7`：

```yaml
- insert:
    - id: ui-skin-maid-atelier
      name: '@dsh-external/dsh-client-ui-skin-maid-atelier'
```

- 官方 patch 行形态（含 config/inject/disabled）与「整段替换」语义：`deepseek-harness/packages/bundle/web-app/cordis.patch.yml:5-6,47-49,123-126,137-145,314-315`。
- 安装 & reconcile：`deepseek-harness/apps/cli/src/plugin.ts:36-45`（exportsPatch）、`:59-91`（reconcile）、`:120-157`（runPlugin = pnpm forwarder）。
- profile 布局/模板/兜底：`deepseek-harness/packages/boot/app-boot/src/profile.ts:104-117`（resolveProfileDir + PROFILE_TEMPLATES：web/headless）、`:127-168`（initProfile）、`:223-255`（healProfilesModuleFallback）。

### 本平台怎么用

T8 `ensure_home_config` 写 `profiles/web/cordis.patch.yml` 单行 id 定向覆盖（id=`naoker-platform-connector`，config 三字段）；插件包 = 上述最小 package.json + 一行 `insert` 的 `cordis.patch.yml`。

---

## 3. web profile 会话库：真实存储路径与结构

### 结论

**web profile 默认没有落盘 SQLite。** 会话持久化是 JSONL（默认 zstd 压缩）：

- 路径：`<DSH_HOME>/sessions/<项目key>/<会话key>/session.jsonl.zstd`
  - `<DSH_HOME>`：环境变量 `DSH_HOME`（平台=`var/dsh/<uid>/`），缺省 `~/.dsh`（`packages/util/home-paths/src/index.ts:87-91`）；
  - `<项目key>` = cwd 的路径编码（如 `--C-Users-u--`，`persistence-jsonl/src/format.ts:147-167`），cwd 缺省 → `_no-cwd`；`<会话key>` = session id 的安全编码（`:169-191`）。
- **文件首行 header = 「会话表」**：`{type:'session', version, id, createdAt(epoch ms), cwd, parentSession, seedLength, origin?, delegationDepth, agentPreset}`（`format.ts:33-63`）。**无 title 列**。
- **标题**：日志事件 `session/title`（payload `{title, basedOn, source}`——`packages/session/session-title/src/index.ts:60-67`），另有同名投影 `title`。
- **turn/消息计数**：事件流计数——turn=`turn/start` 条数；消息=`user/message`+`assistant/message` 条数；现成投影 `sessionStats`（`packages/session/session-stats/src/index.ts:2-5,28`，整日志 turn/step 计数，web patch 行 `session-stats` 已挂）。
- 投影缓存永续形态：`<DSH_HOME>/storages/<unit>.json`（`storage-json` root=`dshHomePath('storages')`，web patch `:54-62`；每 unit 一个文件，`packages/storage/storage-json/src/index.ts:64-65`）。
- 唯一的 SQLite（搜索派生索引 `session-query-sqlite`）在 web profile 被配成 `path: ':memory:'` + `openAt: never`（web patch `:30-33`）——**磁盘上不存在该库**。若部署改持久化，schema（`packages/session-query/session-query-sqlite/src/schema.ts:16-25,103-139`）：

```sql
CREATE TABLE persisted_sessions (
  id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at INTEGER NOT NULL,
  cwd TEXT, parent_session TEXT, seed_length INTEGER, delegation_depth INTEGER,
  agent_preset TEXT, revision TEXT NOT NULL, generation INTEGER NOT NULL) STRICT
```

  另有 fts5 虚拟表 `persisted_docs(text, session_id, seq, type, time, ...)`；application_id `0x44534851`（`schema.ts:11`）；**仍无 title/正文列**（在 events 的 data 里）；宿主行级 `journalMode` 默认 `wal`（`src/index.ts:202`）。

- 备选「SQLite 会话存储后端」`session-persistence-sqlite`（**不在 web bundle 里**；web 用 jsonl）：`sessions(id,version,created_at,cwd,parent_session,seed_length,origin,delegation_depth,agent_preset,incarnation,revision)` + `events(session_id,seq,type,time,data,source_event_seqs,surface_op,ignorable)`（`resources/sql/schema.sql:1-31`，SCHEMA_VERSION=17）。`data` 为事件 JSON，title/usage 都在其中。

**只读打开（Python）姿势**：

```python
import sqlite3
con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # 只读
```

- **本计划实现结论**：T9 同步源 = **扫 JSONL 日志目录**（不是 SQLite）。字段映射：`id ← header.id`；`title ← 最新 session/title 事件`；`turn_count ← turn/start 计数`；`last_activity ← 最后一条事件 time`；正文永不复制（Constraint #6）。
- 若他处开 SQLite：`mode=ro`；WAL 库未 checkpoint 数据在 `-wal`，ro 可读，但**禁用 `immutable=1`**（=「绝无写者」，实例存活时最危险）且不要 `wal_checkpoint`、不要 vacuum。

### 证据

- jsonl 后端行：`deepseek-harness/packages/bundle/base/cordis.patch.yml`（`session-persistence-jsonl` 行）：

```yaml
- id: session-persistence-jsonl
  name: '@deepseek-ai/dsh-session-persistence-jsonl'
  config:
    root: !!js dshHomePath('sessions')
```

- web 不覆盖该行、只重配 sqlite 索引为内存/never：`deepseek-harness/packages/bundle/web-app/cordis.patch.yml:30-33`。
- 路径构造：`deepseek-harness/packages/session/session-persistence-jsonl/src/format.ts:24-26`（`.jsonl.zstd`/`.jsonl`）、`:147-167`（projectKey）、`:176-208`（projectDir/sessionDir/logPath）；header 结构 `:33-63`；零副作用定位 API `packages/session/session-persistence-jsonl/src/index.ts:171-174`（`locate(meta)`）。
- home 解析：`deepseek-harness/packages/util/home-paths/src/index.ts:87-100`（显式路径 > `$DSH_HOME` > `~/.dsh`）。
- 事件边界与 usage：`deepseek-harness/packages/core/session/src/types.ts:269-277`（`assistant/message` 可选 `usage`；turn/start、turn/end 同属 SessionEventMap）。
- sqlite 持久化后端 schema：`deepseek-harness/packages/session/session-persistence-sqlite/resources/sql/schema.sql:1-31`。

### 本平台怎么用

T9 `sync_user_sessions` 遍历 `var/dsh/<uid>/sessions/**/session.jsonl.zstd`，解码后首行取 header、扫行聚合 title/turn/时间戳。

---

## 4. 无头任务姿势：CLI headless vs Python SDK + token usage 证据

### 结论

- **CLI**：`dsh --profile headless "任务文本"`——一等 profile（模板 = base+headless bundle，`profile.ts:114-117`），语义「回答一个任务、打印最后一条 assistant 消息、退出」（`packages/bundle/headless/src/startup.ts:33-40`；`:53` 空任务 usage error）。适合一次性冒烟/跑批：stdout = 最终回答，退出码 = 成败。
- **Python SDK**：`pip install deepseek-harness-sdk`；`with DeepSeekHarness(provider=…, model=…) as h: result = h.run("task")`。底层启动捆绑的单文件 `dsh-jsonrpc-agent`（JSON-RPC over stdio）。**注意：0.1.1-rc.2 没有 `sdk` profile**（`PROFILE_TEMPLATES` 只有 web/headless）——SDK 不是 `dsh --profile sdk`，而是独立捆绑运行时 + `DSH_CORDIS_CONFIG` 注入自定义组合。
- **RunResult 无 usage 字段**：`RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`（`python/sdk/src/deepseek_harness/api.py:38-45`）。**usage 在 `events` 里**：`assistant/message` 事件带 `usage?: TokenUsage {inputTokens, outputTokens, cacheReadTokens?, cacheWriteTokens?, reasoningTokens?}`（`packages/llm/llm/src/types.ts:135-141`；挂载点 `packages/core/session/src/types.ts:277`）。
- **三期计费候选证据（本期只记录，不实现）**：
  1. **首选：会话 JSONL 中每条 `assistant/message.usage`**——web/headless/SDK 三形态同源（同一 session 事件层），分桶齐（input/cacheRead/cacheWrite/output/reasoning）。
  2. **次选：token-meter 投影** `tokenUsage`/`contextPressure`（`packages/llm/token-meter/src/projection.ts:8-70`、`usage-projection.ts:19-23` tokenUsage 状态 schema）；base/web bundle 与 SDK 默认 cordis（`examples/jsonrpc-agent/cordis.yml:80-81`）都挂 token-meter；web 下经 `session-projection-cache` 持久化在 `<home>/storages/`。缺点：是「请求时累计快照」非原始流水，compaction 不报 usage。
  3. RunResult 无字段 —— SDK 调用方需自行对 `events` 做 sum。
- 结论：计费口径应以 `usage` 事件为原始数据（每条 assistant/message 或每个 usage chunk 累加），投影缓存只作对账。

### 证据

- headless CLI 定义：`deepseek-harness/packages/bundle/headless/src/startup.ts:31-41`（`.name('dsh --profile headless')`、`.description('Answer one task, print the final assistant message, and exit.')`、`.argument('[task...]')`）。
- SDK：`deepseek-harness/python/sdk/src/deepseek_harness/api.py:38-45`（RunResult）、`:56-84`（config→env：`session_root`→DSH_SESSION_ROOT、`base_url`→DEEPSEEK_BASE_URL、`api_key`→DEEPSEEK_API_KEY）、`:117-124`（run）、`:176-183`（final_response/finish_reason 从 events 派生）；README（`python/sdk/README.md`：「The runtime inherits normal DeepSeek Harness environment variables such as DEEPSEEK_BASE_URL and DEEPSEEK_API_KEY」）。
- profiles 只有 web/headless：`deepseek-harness/packages/boot/app-boot/src/profile.ts:114-117`。
- usage 事件：`deepseek-harness/packages/core/session/src/types.ts:269-277`：

```ts
'assistant/message': { turn: number; step: number; message: AssistantMessage; usage?: TokenUsage; interrupted?: true }
```

- TokenUsage 字段：`deepseek-harness/packages/llm/llm/src/types.ts:135-141`；`usage` chunk：同文件 `:318`。
- token-meter：`deepseek-harness/packages/llm/token-meter/src/usage-projection.ts:19-23`（桶）、`projection.ts:8`（durable cumulative）；SDK 组合挂载先例 `deepseek-harness/examples/jsonrpc-agent/cordis.yml:80-81`（`id: token-meter`）。

### 本平台怎么用

本期无头任务仅作冒烟（T12 用 headless CLI）；T9 同步器顺手从 JSONL 归集 `assistant/message.usage` 不落平台库之外（只记映射），三期直接建表消费。

---

## 5. `--trusted-host`：校验什么、默认值、反代场景传什么

### 结论

- `--trusted-host <authority...>`（可重复，`host` 或 `host:port`）= **`/api` 浏览器信任围栏**额外放行的权威（`packages/bundle/web-app/src/startup.ts:54`：`'extra authority the /api browser-trust fence accepts (host or host:port; repeatable)'`）。
- 围栏三段校验（`packages/client/connection/src/api-request-trust.ts:96-123`）：
  1. **Host 头**必须为 loopback 主机名 **或** 命中 `--trusted-host` 条目（`isTrustedAuthority`：带端口条目精确匹配端口，不带端口条目匹配任意端口，`:80-88`）——防 DNS rebinding；
  2. `sec-fetch-site: cross-site` 一律 403（`:111`）；
  3. 携带 `Origin` 时必须与 Host 完全相同源（`:116-122`）；`null` origin 拒绝。
- **默认值 = 空数组 ⇒ 仅 loopback**（`startup.ts:84`）。`resolveLanTrust` 只在 `--host 0.0.0.0` 时自动补 LAN IP 字面量（`web-app/src/index.ts:132-139`），而 **`--host 0.0.0.0` 被明确拒绝**（`startup.ts:74-76`）；故实际默认 = 仅 127.0.0.1/localhost。
- 条目须严格「bare authority」：`harness.internal/path`、`user@host`、隐式端口等非规范写法 load 期即抛错（`api-request-trust.ts:41-58`）。
- 围栏覆盖面：`/api` HTTP 前缀（`client/connection/src/index.ts:161-173`）+ `/api/events/mux`、`/api/events/host` **WebSocket upgrade**（`:181-194`）。**特权 RPC 方法额外用空名单（=仅 loopback）再查一遍**（`:145-149`：`settings.*`、`credentials.*`、`host.*`、`agentPreset.*`、`llm.discoverModels` 等 PRIVILEGED_METHODS）——平台反代时这些方法恒 403，勿纠结。
- **反代场景**（浏览器 → 平台 FastAPI 域 → 127.0.0.1:<port> 的 DSH）：

```
dsh --profile web --host 127.0.0.1 --port <port> --trusted-host localhost:3000 --trusted-host app.internal --no-open
```

  **严禁改 Host 头转发**：转发需保留平台权威 Host（Host=平台域），Origin 才与 Host 同源；若把 Host 改成 127.0.0.1 而 Origin 仍是平台域 ⇒ Origin≠Host 被拒。dev 前端域即 Global Constraint #5 的 `localhost:3000`。

### 证据

- flag：`deepseek-harness/packages/bundle/web-app/src/startup.ts:46-60`（`--trusted-host <authority...>` 帮助文案）、`:74-76`（--host 0.0.0.0 报错文案）、`:80-85`（trustedHosts 默认 `[]`）。
- 行配置链路：`deepseek-harness/packages/bundle/web-app/cordis.patch.yml:137-144`（web-runtime.trustedHosts = webStartup.trustedHosts）、`:164-171`（connection.trustedHosts = webRuntime.trustedHosts）。
- 围栏实现：`deepseek-harness/packages/client/connection/src/api-request-trust.ts:41-58`（assertTrustedAuthority）、`:73-88`（isTrustedAuthority）、`:96-123`（isTrustedApiRequest）。
- 挂载 + WS + 特权重查：`deepseek-harness/packages/client/connection/src/index.ts:145-149,161-170,181-194`。
- LAN 自动填充：`deepseek-harness/packages/bundle/web-app/src/index.ts:132-139`；测试样例 `packages/bundle/web-app/tests/trusted-hosts.spec.ts:24-32`。

### 本平台怎么用

`spawn_command` 固定 `--host 127.0.0.1` + `--trusted-host <dsh_trusted_hosts 列表>`（T4 配置）；代理端原样透传 Host/Origin。

---

## 6. `DEEPSEEK_API_KEY` 注入：env 直生效 + 优先级 + 写文件姿势

### 结论

- **子进程环境变量注入直接生效，且优先级最高、无需任何写盘**。凭据解析链路（`packages/credentials/credentials-local/src/index.ts:1-21,557-571,617-625`）：

```text
继承的进程环境（read-only，WINS）
> $DSH_HOME/.credentials.yaml（provider 管理、可写）
> <调用 cwd>/.env（只读兜底）
> $DSH_HOME/.env（只读兜底）
```

  `resolve()` 第一优先 `launchEnvironmentOf(ctx).getFrom(ref, ['process'])`——非空即 `{value, source:'env'}`。平台 spawn 时传 env 即可；且 llm-deepseek **每个请求才解析一次**（`llm-deepseek/src/index.ts:100-104`：`a missing API key resolves through Config.apiKeyEnv at each request`），无缓存。
- **模型 provider 配置读哪里**：`$DSH_HOME/settings.yaml`（`settings-file` 默认 home 下 `settings.yaml`——`packages/settings/settings-file/src/index.ts:51-56`）的 `llm-deepseek:`/`llm-pi-ai:` 段（base patch `settings:` 行注释：`a llm-deepseek: or llm-pi-ai: section there overrides the adapter entries below ... is what the web Models page writes`）。字段可选：`apiKeyEnv`（默认 `DEEPSEEK_API_KEY`，`llm-deepseek/src/index.ts:79,106-110`）、`baseURL`、`thinking`、`reasoningEffort`、`maxTokens`…。**settings.yaml 永远只存引用（env 名），不存密钥值**。
- **若必须写凭证文件**（无 env 透传的容器场景）：`$DSH_HOME/.credentials.yaml`：

```yaml
version: 1
refs:
  DEEPSEEK_API_KEY: sk-xxx
```

  最小安全姿势：文件 `0600`、目录 `0700`（provider 写路径自动带 0600/0700：`:683,699,767-778`；读文件前校验 group/other 权限位为 0——`assertOwnerOnly` `:96-146`，**仅 POSIX，Windows 跳过**）。注意：**env 与文件不能并存**——存在 env 时 `set()` 会被拒（`assertUnshadowed` `:794-801`：「supplied read-only by the launching environment」），且即使写了 env 仍优先。
- 平台容器内凭证建议：`DSH_HOME` 整树 `0700`、属主=运行容器进程 uid（非 root）；`.credentials.yaml` `0600`；密钥只经 spawn env 传递、绝不写日志（上游还有「env 不落入浏览器」先例断言 `packages/bundle/web-app/tests/web-app.spec.ts:322-336`）。

### 证据

- 优先级原文：`deepseek-harness/packages/credentials/credentials-local/src/index.ts:5-21`（含 `The inherited environment wins because DEEPSEEK_API_KEY=… dsh, a CI secret, or a container -e is this run's explicit intent`）。
- resolve 实现：同文件 `:557-561`（inherited → process env）、`:617-625`（env → file → dotenv 次序 return）；`describe` `:627-639`（env 层 `writable:false`）。
- 写文件权限：同文件 `:699`（`writeFileAtomic(..., { mode: 0o600, dirMode: 0o700 })` 先例）、`:96-146`（assertOwnerOnly）。
- settings 默认路径：`deepseek-harness/packages/settings/settings-file/src/index.ts:51-56`；llm-deepseek NS：`deepseek-harness/packages/llm/llm-deepseek/src/index.ts:20,78-79,106-110`（`NS = settingsNamespace('llm-deepseek')`、`DEFAULT_API_KEY_ENV = 'DEEPSEEK_API_KEY'`）。
- base patch settings 行注释：`deepseek-harness/packages/bundle/base/cordis.patch.yml`（`settings:` 行块注释：`$DSH_HOME/settings.yaml, hot-reloaded … overrides the adapter entries below … what the web Models page writes`）。

### 本平台怎么用

T8 `spawn_env(settings, token)` 返回 `{DEEPSEEK_API_KEY: …}`（仅返回值，不落盘，Constraint #7）；若某天必须落盘 → `var/dsh/<uid>/.credentials.yaml` 0600。

---

## 与计划假设的偏离（T2 考古结论对 spec/计划的修正）

1. **web profile 会话库不是 SQLite**：JSONL（zstd）`<home>/sessions/…` 才是事实持久层；`session-query-sqlite` 在 web 里是 `:memory:`+`openAt:never`，磁盘无文件。T9 同步应扫 JSONL（计划 T3/T9 的「以 T2 实测 schema 为准」出口命中此修正）。
2. **没有 `sdk` profile**：Python SDK 走捆绑 `dsh-jsonrpc-agent`（JSON-RPC/stdio），非 `dsh --profile sdk`。
3. **RunResult 无 usage 字段**：usage 只出现在会话事件 `assistant/message.usage`（TokenUsage）与 `tokenUsage` 投影；T9 顺手归集、三期接账。
4. **`--trusted-host` 默认空（仅 loopback）**；`--host 0.0.0.0` 被拒绝；LAN 字面量只在该失败路径下派生——平台必显式传权威。
5. **patch config 是「整段替换」非合并**——T8 生成行必须完整重复 config 全字段（平台侧三字段一次写齐）。

---

## 7. 平台侧接点（T7 实读 backend 源码，connector 按此实现）

> 本节为 T7 对 `backend/app/api/files.py`、`api/feishu.py` 与 `services/feishu/*` 的实读结论；平台源码路径相对仓库根 `backend/` 写。
> **已标记的平台侧缺口（双端校验、飞书文档索引端点）由后续 backend 任务补齐，connector 契约先行并逐条记录差异。**

### 7.1 统一响应壳

- 所有端点经 `success(request, data)` 返回 `{data: <payload>, message: "OK", request_id}`（`backend/app/schemas/common.py:16-23`）；connector 一律解 `body.data`，HTTP 4xx/5xx 抛错。

### 7.2 鉴权现状（两处缺口，后端待办）

- `get_current_user` **只认 Cookie `access_token` JWT**（`backend/app/core/dependencies.py:16-17`）；全 backend 无 `X-Platform-Token` 的消费点（grep 仅 `config.py:87` 的 `dsh_platform_token_ttl_seconds` 存在）。
- 结论：connector 契约携带 `X-Platform-Token`（平台签发的短时 token）+ `X-Dsh-Platform-User`（用户 id），由后端新增「双端校验」依赖（平台 token 校验 + 属主校验）后生效；**当前直接调用会 401**，属已知待办，非实现错误。

### 7.3 `platform_search_files(query, file_type?)` —— 真实接点

- **端点**：`GET /api/files`（`backend/app/api/files.py:211-239` list_files）。
- **参数**（全部可选，Query）：`folder_id`、`keyword`、`media_type`、`page`（默认 1）、`page_size`（默认 20，上限 100）；默认按当前用户 owner 过滤。
- **响应 data**：`{items: [FileObjectResponse], page, page_size, total}`（`backend/app/schemas/file.py:32-54`）；FileObjectResponse 字段：`id, owner_user_id, folder_id, filename, original_filename, media_type, size_bytes, sha256, extracted_text, preview_status, source_attachment_id, created_at, updated_at`。
- **映射**：`file_id ← id`、`title ← filename`（无独立 title 字段）、`mime ← media_type`。
- connictor 实际调用：`GET {platformBase}/api/files?keyword={query}&media_type={file_type}&page_size=20`（file_type 缺省不带参数）。

### 7.4 `platform_read_file(file_id)` —— 真实接点

- **端点**：`GET /api/files/{file_id}/preview`（`backend/app/api/files.py:337-370` preview_file）。（**无** `/content` 端点；计划预期的 `GET /api/files/{file_id}/content` 在 files.py 不存在，以 preview 为准。）
- **响应 data 三分支**：
  - `{type: "text", content: str}` —— `text/*`、`application/json`（`_extract_text` 侧已截断 100KB，files.py:49-67）与 docx/xlsx/pptx（`extract_file_text` 提取，files.py:359-369）；
  - `{type: "stream", url: "/api/files/{id}/download"}` —— video/audio/image/application/pdf（流式，不能直接转文本）；
  - `{type: "unsupported"}` —— 其余类型。
- **契约缺口（记录）**：preview 响应**不含文件名/标题**，且不存在单文件元数据端点（`GET /api/files/{id}` 无对应路由）；connector 以 `file_id` 兜底 `title`，权威标题来自 search 结果（`filename`）。

### 7.5 `platform_get_docs(query?, take?)` —— 飞书侧事实与契约

- **feishu.py 现有路由全集**（`backend/app/api/feishu.py:54-261`）：`configs/status`、`configs` CRUD、`configs/{id}/activate`、`oauth/start`、`oauth/callback`、`status`、`connection`（DELETE）——**不存在文档列表/检索端点**。
- **FeishuClient**（`backend/app/services/feishu/client.py:87-131`）仅有 `read_document`/`create_document`/`add_blocks`/`update_block`/`set_public_permission`（直连 `open.feishu.cn/open-apis`）；**无 list/search**。
- **FeishuService**（`backend/app/services/feishu/service.py:120-151`）同上；文档操作需用户级 feishu access_token（OAuth 存 `FeishuToken`，AES-GCM 加密），agent 内的 feishu 工具经 `tool_executor._feishu_action`（`backend/app/services/agent/tool_executor.py:1266-1295`）内部调用 —— **均非本 connector 可得的 HTTP 面**。
- **connector 冻结契约**：`GET {platformBase}/api/feishu/documents?query={q}&take={n}` → data `{docs: [{doc_id, title}]}`。平台侧实现（后续 backend 任务）应：以 `X-Dsh-Platform-User` 查 `FeishuToken` → 经 FeishuClient 增加 list 方法调飞书 drive 列表 → 映射 `doc_id ← file_token`、`title ← name`。已选择的 `take` 语义：默认 10，connector 侧夹逼到 1..50。
- **差异记录**：该端点当前不存在（feishu.py 实读无此路由），T7 按上述契约实现并以 fetch mock 单测；提交信息已注明。

### 7.6 请求头契约（connector → 平台）

```
X-Platform-Token: <platformToken>       // 必带，平台短时 token（T4 dsh_platform_token_ttl_seconds）
X-Dsh-Platform-User: <userId>           // 必带，平台用户 id（供后端属主校验）
Content-Type: application/json          // 统一带；GET 不带 body
```

- 三个工具全部 GET，无 body；工具响应不含任何 token/密钥（token 只在请求头）。

---

## 8. DSH 客户端能力核验（T1 spike：选择器与隐藏机制）

> 依据 vendored 上游 `deepseek-harness/packages/client/*`（0.1.1-rc.2，只读）、已装构建产物 `%APPDATA%\npm\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\*`、活动皮肤 `@dsh-external/dsh-client-ui-skin-maid-atelier`（profile=desktop）。
> **本机无浏览器自动化（playwright/puppeteer 均未安装）**：计划 Step 2/3 的「DevTools 注入实测」改为**源码级考证**——所有 DOM 结构/选择器从源码与已装构建推出并给出 文件:行号；标注 `live verification pending` 的项留到 T3/T10 在真实实例验证。
> 实例存活探测：`http://127.0.0.1:3163/` 返回 200（本机 web profile，`~/.dsh/profiles/desktop`）。

### 8.1 结论（机制定稿）

1. **隐藏机制 = 零宽隐藏 + 同时折叠 frame 网格轨（对计划原写法的必要修正）**。零宽三件套（`width:0; min-width:0; overflow:hidden`）只作用于列元素本身；`SIDEBAR_COLUMN_SELECTOR` 命中的 `.sidebarCol` 是 AppFrame 的 **grid item**，其轨道由 frame 的内联 `grid-template-columns: ${cols.sidebar}px minmax(0, 1fr) ${cols.details}px` 决定，且关闭态轨道 = `SIDEBAR_COLLAPSED` 56px（**永不为 0**）——只设列宽 0 会残留一条空轨道（违反验收「无残留空列」「会话区铺满」）。隐藏例程必须同时把 frame 第一轨置 0（见 8.3）。**不替换 `sidebar` 槽**：替换会连带销毁其声明的 `sidebar.workspaces`/`sidebar.settings` 等内部槽（ui-layout/src/client/index.ts:39-49 明确警告）。
2. **设置面板在零宽下仍可见**：设置外壳把 `position:fixed; inset:0; z-index:1000` 的 overlay 渲染为 `sidebar.settings` 槽 occupant 的**普通 DOM 后代**（非 portal），`SettingsRoot.tsx:62-64` + `SettingsRoot.module.css:51-58`；fixed 定位相对视口，祖先无 `transform/filter/perspective/contain`（AppFrame/SidebarRoot CSS 实读无这些属性）⇒ 不受侧栏列 `overflow:hidden` 裁剪。`live verification pending`（T3/T10 实测 fixed 逃逸与 z-index）。
3. **目录选择流程零宽下无需恢复侧栏宽度**：browse occupant 用 ui-primitives `Modal`，其实现 `createPortal(..., document.body)`（ui-primitives/src/Modal.tsx:55,85）⇒ 弹窗在 body 下，与侧栏裁剪无关；native occupant 是 renderless 组件，直接驱动宿主 OS 选择器（ui-directory-picker-native/src/client/index.ts:26-39）⇒ 更与 DOM 无关。激活哪个 occupant 由 web-app bundle 的 `directory-picker` 行 `@deepseek-ai/dsh-host-directory-picker-auto` 在启动时解析（`deepseek-harness/packages/bundle/web-app/cordis.patch.yml:96-97`）——插件不得假定其一。`live verification pending`（本机实际激活的是 native 还是 browse）。
4. **过滤菜单与新建工作区菜单均已 portal 到 body**（`Menu` 的 `portal` 模式，Menu.tsx:299），零宽下可正常显示：过滤菜单 WorkspaceBrowser.tsx:178；WorkspacePickFlow 菜单 WorkspacePicker.tsx:194。`live verification pending`。
5. **搜索不走原生搜索框**：原生搜索输入只驱动侧栏树且会被裁剪；插件经桥直接调用 `ctx.sessions.search(query, signal)`（返回 `{ok, value}` 信封，ui-workspace/src/client/index.ts:59-63），平台侧自渲染结果。
6. **触发按钮的可用性前提**：过滤按钮为 wide 态专属（`{wide && <ViewOptionsMenu/>}`，WorkspaceBrowser.tsx:1076-1084）；＋新建按钮仅当 `sidebar.workspaces.directoryFlow` 槽被 occupant 占据时渲染（`directoryFlowAvailable`，WorkspaceBrowser.tsx:1088-1102）。零宽 CSS 不改变 shell 传入的 `wide`（`wide = !collapsed || !settled` 由 layout store 驱动，SidebarRoot.tsx:52-58）⇒ wide 内容保持挂载，两按钮都在 DOM 中。点击用程序化 `.click()`，与是否被裁剪无关；菜单 portal 后从锚点 rect 定位。
7. **观察组件可注册进 `shell.overlay`**：该槽是 `kind:'list', scope:'root'`（ui-layout/src/client/index.ts:83,126），渲染在 `data-shell-overlay` 层（AppFrame.tsx:193-195）；槽锚点 wrapper 为 `display:contents`（scoped-slots.tsx:652,676），渲染 `null` 的观察组件不占布局、不拦截指针（层 `pointer-events:none`，子项 auto，AppFrame.module.css:110-119）。注册进该槽的组件拿到全局 `useSessions`/`useWorkspaces` 标准 hooks（PropsRuntime<'shell.overlay'>，同 AppFrameProps 的用法 AppFrame.tsx:87-97）。

### 8.2 客户端服务调用链核验（计划 Step 1，行号以实读为准）

| 调用 | 证据（vendored） | 备注 |
|---|---|---|
| `ctx.sessions.open(sessionId)` | `ui-workspace/src/client/index.ts:77`（`open: (sessionId) => { ctx.sessions.open(sessionId) }`） | 计划写 :76，实际 :77 |
| `ctx.workspaces.startSession(workspaceId?)` | `ui-workspace/src/client/index.ts:76`（`startSession: (workspaceId) => { ctx.workspaces.startSession(workspaceId) }`） | 计划写 :74，实际 :76；`ui-sidebar/src/client/index.ts:37` 同款调用 |
| `ctx.sessions.search(query, signal)` → `{ok, value}` | `ui-workspace/src/client/index.ts:59-63`（`const result = await ctx.sessions.search(query, signal); if (!result.ok) throw …; return result.value`） | 另有 `ctx.sessions.searchResultLimit` :79 |
| `ctx.slots.register({name}, Component)` / `ctx.slots.inject(hole, cb)` | `ui-workspace/src/client/index.ts:113-131`（`inject('sidebar.workspaces', () => register({name, children, store, inject, locale}, WorkspaceBrowser))`；picker 同 :123-131） | 跨包注册的标准姿势 |
| `useSessions` / `useWorkspaces` 标准 hooks | `WorkspaceBrowser.tsx:747-748`（props 解构）、:258/:780（`useSessions` 用法）、:769-771（`useWorkspaces` 用法）；类型证据 `contract/slots.ts:143-149`（`PropsRuntime<'sidebar.workspaces'>`） | 框架按 `PropsRuntime` 注入，注册进 root 作用域槽的组件同样获得 |
| `shell.overlay` 声明与 kind | `ui-layout/src/client/index.ts:83`（SlotMap：`{kind:'list'; scope:'root'}`）、:126（register children）；渲染 `AppFrame.tsx:23`（PropsRenderSlots 含 `'shell.overlay'`）、:193-195 | list 槽按注册序排列，支持「返回 null 的观察组件」 |

### 8.3 隐藏机制的关键修正：网格轨（写进 T3/T4 实现约束）

- 命中元素：`AppFrame.tsx:173` `<div className={css.sidebarCol}>`（CSS `AppFrame.module.css:25-30`，含 `border-right:1px`）；已装构建里 class 为 `.pI_x6G_sidebarCol`（`dsh-client-ui-layout/lib/client.js` CSS 区，含 `sidebarCol` 子串）⇒ `[class*='sidebarCol']` 命中；`[data-pane='sidebar']` 在 0.1.1-rc.2 vendored 源码与已装构建中**均无输出**（全仓/构建 grep 无命中），保留为皮肤同款前向兼容臂。
- 轨道来源：`AppFrame.tsx:168` 内联 `gridTemplateColumns: ${cols.sidebar}px minmax(0,1fr) ${cols.details}px`；`computeColumns` 关闭态返回 `SIDEBAR_COLLAPSED=56`（`columns.ts:29,64,76`）⇒ 轨道永不为 0。
- **实现约束**：隐藏例程 = ①列元素 `width:0;min-width:0;overflow:hidden;border-right:none`；②frame（`column.parentElement`）第一轨置 0（如读 `getComputedStyle(frame).gridTemplateColumns` 取第三轨后写 `0px minmax(0, 1fr) <details>px`）。AppFrame 每次 store 变化都会重写该内联 style（AppFrame.tsx:168）⇒ 需 MutationObserver 监听 frame `style` 属性重放覆盖；恢复时移除覆盖并还原列内联样式。
- 被否备选：`display:none`（连坐 fixed 设置面板）、替换 `sidebar` 槽（销毁内部槽）、`ctx.layout.setSidebar(0)`（渲染 56px rail 且 wide 内容在 settle 后卸载，不是零宽）。

### 8.4 触发选择器定稿（计划 Step 3/4）

| 常量 | 值 | 证据与说明 |
|---|---|---|
| `SIDEBAR_COLUMN_SELECTOR` | `:is([data-pane='sidebar'], [class*='sidebarCol'])` | 与活动皮肤 `dsh-deep-whale/maid-atelier/src/client/index.ts:45` 同款；实测命中臂 = `sidebarCol` |
| `SETTINGS_TRIGGER_SELECTOR` | `[data-slot='sidebar.settings'] > :is(button, [role='button'])` | 槽锚点由渲染器统一注入（`ui-renderer/src/client/scoped-slots.tsx:669-679`：`<div data-slot=… style="display:contents">`）；occupant 首个子元素即触发按钮 `SettingsRoot.tsx:144-152`；皮肤同款选择器 `maid-atelier/src/client/index.ts:47` |
| `WORKSPACE_REGION_SELECTOR` | `[data-slot='sidebar.workspaces']` | `SidebarRoot.tsx:193` renderSlot + `ui-sidebar/src/client/index.ts:50` 声明；锚点同上 |
| `FILTER_TRIGGER_SELECTOR` | `[data-slot='sidebar.workspaces'] button[aria-label='视图选项'], …[aria-label='View options']` | `WorkspaceBrowser.tsx:181-188`（`IconPersonalizationOutline16` + `aria-label={t('viewOptions.label')}`）；文案 zh/en = `locales.ts:13,82`。图标 SVG 无稳定属性，aria-label 是唯一稳定判别；字典只发 zh/en 两套（0.1.1-rc.2）故双写覆盖 |
| `ADD_WORKSPACE_TRIGGER_SELECTOR` | `[data-slot='sidebar.workspaces'] button[aria-label='添加工作区'], …[aria-label='Add workspace']` | `WorkspaceBrowser.tsx:1090-1100`（`IconProjectAddOutline16` + `aria-label={t('workspace.add')}`）；文案 zh/en = `locales.ts:24,93`；仅 directoryFlow 槽被占据时渲染（:1088） |

### 8.5 待 live 验证项（留给 T3/T10 真实实例）

1. 零宽 + frame 轨道置 0 后：侧栏无残留、会话区铺满、无 1px 接缝（含 AppFrame 重渲染后覆盖是否被 MutationObserver 保住）。
2. 设置触发按钮点击后 fixed overlay 是否全屏可见（不受裁剪/层叠上下文困住；皮肤 AGENTS 记录过 WebKit fixed 困在 stacking context 的坑）。
3. 目录选择弹窗实际形态（native OS 选择器 vs browse Modal）及零宽下的可见性。
4. 过滤菜单/新建菜单 portal 定位在零宽锚点下是否可读可用。
5. 活动 locale（zh/en）确认——选择器已双写覆盖，但 T10 应确认运行实例文案命中哪一支。

### 8.6 本平台怎么用

T3/T4 的隐藏例程按 8.3 双步实现（列零宽 + frame 第一轨归零 + border 清除 + style 观察者）；命令桥按 8.2 的服务调用链实现（new/select/search/filter/add-workspace/open-settings）；观察组件注册进 `shell.overlay`（8.1-7）用 `useSessions`/`useWorkspaces` 上行推送；选择器统一从 `packages/server-connector/src/client/selectors.ts` 导入，禁止散落字面量。

---

## 9. DSH 工作区右侧留白：真实实例实测与布局修正（2026-09-18）

### 结论

留白根因**不是**「右侧 details 轨残留」，也**不是**「内容列自身宽度限制」，而是侧栏隐藏例程把**中间轨冻结成像素**：

- `replay()` 读 `getComputedStyle(frame).gridTemplateColumns`（已用值，如 `280px 1290px 0px`），`zeroFirstTrack` 只把第一轨置 0 后写回内联 style，`minmax(0, 1fr)` 这一逻辑表达式丢失 → 中间轨固定为 1290px；frame 宽 1570px，右侧空出 280px（恰为 `SIDEBAR_DEFAULT`）。
- 修正（`src/client/sidebar-hide.ts`）：① `zeroFirstTrack` 置 0 第一轨后，若第二轨是纯像素值则恢复为 `minmax(0, 1fr)`（末轨 details 原样保留）；② `replay()` 优先读**内联逻辑值**（AppFrame 写的 `${sidebar}px minmax(0, 1fr) ${details}px`），仅内联为空时回退 computed。
- 为什么重放源必须是内联值：`.frame` 有 `grid-template-columns` 过渡（`AppFrame.module.css`），computed 在过渡期间仍返回旧宽度；实测用 computed 重放会把刚写下的 details 轨立刻撤销回 0（details 面板打不开/窗口缩放被卡住），同时把中间轨冻成像素。
- 计划原拟的 `APP_FRAME_SELECTOR` / `CONVERSATION_COLUMN_SELECTOR` 未新增：实测确认缺陷在既有重放逻辑内部，frame 仍按 `column.parentElement` 获取、列仍按 `[class*='sidebarCol']` 命中，无需新选择器。

### 实测数据（headless Edge + CDP；viewport 1570×805；临时探针命令 `probe-layout` 已按计划移除）

修复前：

- frame = `div.pI_x6G_frame`，`data-details-collapsed=true`，内联 `grid-template-columns: 0px 1290px 0px`，rect 1570×805（= body 宽，无宽度限制）
- 子元素：`pI_x6G_sidebarCol` w=0；`pI_x6G_centerCol` x=0 w=1290（rightGap=280）；`pI_x6G_detailsCol` w=0（右轨无残留）
- 结论：空白 = 中间轨被冻结后释放不掉的 280px

修复后（构建 → 杀 3163 进程 → 手动拉起 pid 13684 → 复测）：

- frame 内联 `0px minmax(0px, 1fr) 0px`，computed `0px 1570px 0px`；`centerCol` w=1570，rightGap=0
- 选中真实会话（`session-0c059b4a-…`，5 个 nav 事件）后同样满宽
- 模拟 AppFrame 打开 details（写 `280px minmax(0, 1fr) 360px`）：重放后 `0px minmax(0, 1fr) 360px`，details 360px 保留、无右侧空隙；写回关闭态后恢复满宽
- `open-settings` 桥命令：fixed overlay 1570×805、z-index 1000 正常打开，布局不受影响（8.5 第 2 项通过）

### 方法与环境（可复现）

- 本机无 playwright/puppeteer：用系统 Edge `--headless=new --remote-debugging-port=0` + Node 24 内置 `WebSocket` 直连 CDP；临时脚本在 `%TEMP%`，未入库。
- 桥命令在顶层页面内自派发即可（`window.parent === window`）：
  `window.dispatchEvent(new MessageEvent('message', { data: { v:1, type:'cmd', action:'<action>' }, source: window }))`。
- DSH 客户端 bundle 由 web 进程**按请求读盘**（`deepseek-harness/packages/client/modules/src/index.ts:554` `readFile(path)`；rev 是启动时算的 hash，`:472-479`）→ 重新构建后**无需重启实例**，硬刷新页面即加载新代码；本次仍按计划杀进程重启复测。
- 重启姿势：杀 3163 监听进程后，用 spawn 同款命令（`node <dsh>/lib/bin.js --profile web --host 127.0.0.1 --port 3163 --no-open --trusted-host localhost:8010`）+ `DSH_HOME=backend/var/dsh/<uid>` + `DEEPSEEK_API_KEY`（`backend/.env`）手动拉起；后端 `ensure_running` 按端口收养。
- 8.5 遗留项进展：第 1 项（会话区铺满/无残留）与第 2 项（设置 overlay 全屏）已 live 验证通过；第 3-5 项仍未验证。

---

## 10. DSH 会话清理与播种实测（T4，2026-09-18）

> 目标用户 admin `4c40bada-b2e6-45ea-b1b2-a2e43e663072`；脚本 `backend/scripts/dsh_sessions_reset.py`（--dry-run/--clear/--seed）。

### 结论（三条 spike 问题）

1. **删除路径 = 只需删目录**。web 会话列表每次 `list()` 都从磁盘扫描：`packages/session/session-persistence-jsonl/src/index.ts:851-873`（`listProjectDirs` 读 `<root>` 下的项目目录、`listSessionDirs` 读项目目录下的会话目录）；sqlite 查询索引在 web profile 是 `:memory:` + `openAt: never`（§3），无持久索引需要失效。实例停止时删除后，下次启动直接只见剩余会话——**无需 `--profile web`、无需任何索引清理**。实测：清理 1 个项目目录（17 个会话日志）后 `iter_sessions` 归零；播种后磁盘 5 条。
2. **标题 = headless 会写 `session/title`，无需 `--profile web`、无需注入**。每条 headless 会话写两条标题事件：先 `source.kind=fallback`（首条用户消息截断），后 `source.kind=provider`（`session-title-first-prompt-llm` + `deepseek-v4-flash` 生成的精炼标题）；`iter_sessions` 取最后一条 ⇒ 侧栏标题是 LLM 精炼标题而非问题原文（例：问题「为新品制定一份抖音千川投放策略，包含出价与预算分配」→ 标题「新品抖音千川投放策略」）。
3. **落盘布局 = `<home>/sessions/<项目目录key>/session-<uuid>/session.jsonl.zstd`**。项目目录 key 由 cwd 编码（headless cwd=home，本机为 `--C-01_agent_loop_pro-backend-var-dsh-<uid>--`）；`iter_sessions` 的 `rglob` 直接命中，删除单位是项目目录（本机只有一个）。

### 脚本实现与计划假设的差异

- headless 执行器实际是 `DshTaskExecutor`，方法 `run(*, user_id, task, timeout_seconds=None, home_dir=None)`（`backend/app/services/dsh/executor.py:145`），**没有** `DshHeadlessExecutor.run_task`；返回值 `DshTaskResult` **无 `session_id`**——播种靠「运行前后 `iter_sessions` 差集」定位新会话 id 与标题。
- `clear_sessions` 返回**删除的会话日志文件数**（递归计数），不是顶层目录数；真实 home 下顶层只有项目目录，若按顶层计数会得到 1 而不是 17。
- 清理/播种前必须停 3163 实例（避免与 headless 共用同一 home 并发）；播种完成后无需拉起，用户进 `/agent` 时后端会拉起。
- `dsh_sessions` 同步由 `dsh_sync_worker` 每 60s 对 `state=running` 实例执行（`backend/app/workers/dsh_sync_worker.py:21-38`）；播种后无需手动同步，worker 会补上（本次实测 worker 已先同步 4 条）。
