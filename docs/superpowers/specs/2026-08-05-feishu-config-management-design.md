# 飞书 OAuth 配置管理（超管系统内填写 + 员工登录） Design Spec

**Status:** Draft
**Date:** 2026-08-05

## 1. 需求

1. 飞书 OAuth 的 App ID / App Secret 从 `.env` 移到系统内，由**超级管理员**在"连接飞书"弹窗里填写（企业名称 + App ID + App Secret）
2. 支持**多份配置**（表结构可扩展；当前 UI/登录流程先使用"默认配置"一份）
3. 普通员工打开"连接飞书"只看到**登录飞书账号**入口（无配置表单），用默认企业配置 OAuth 登录各自的飞书账号
4. 超级管理员配置完后**同样要走登录流程**（配置与登录分离）
5. Secret 在 DB 中**加密存储**（复用现有 AES-GCM）
6. OAuth 回调 URL 保持固定默认（`settings.feishu_redirect_uri`）

## 2. 现状（已核实）

- `Settings.feishu_app_id/feishu_app_secret/feishu_redirect_uri`（.env）；`FeishuClient.__init__` 直接 `self.settings = get_settings()`，OAuth 三处（`exchange_code`/`refresh_access_token`/`revoke_token`）与 `oauth.py build_authorize_url` 读取 settings
- `app/api/feishu.py`：`/oauth/start`（检查 `feishu_app_id` 非空 → 授权 URL）、`/oauth/callback`（换 token 存 `user_feishu_tokens`）、`/status`、`DELETE /connection`
- `FeishuService.__init__`：`self.client = client or FeishuClient()`（单例，工具层共用）
- 前端 `components/feishu/feishu-connect.tsx`：状态 + 连接（跳 /oauth/start）+ 断开
- 权限模式：`require_super_admin`（agent_audit.py 既有用法）
- 加密：`services/feishu/crypto.py` `encrypt_token/decrypt_token/derive_token_key`

## 3. 数据模型

新表 `feishu_configs`（手写迁移，禁止 autogenerate——混入无关 drift）：

```
id                  uuid PK
name                varchar(100) NOT NULL      -- 企业/应用展示名
app_id              varchar(128) NOT NULL
app_secret_encrypted text NOT NULL              -- AES-GCM 密文（密钥 derive_token_key(jwt_secret)）
is_default          boolean NOT NULL DEFAULT false   -- 当前默认（唯一）
created_at          timestamptz NOT NULL
updated_at          timestamptz NOT NULL
```

不变量：`is_default=true` 最多一行（activate 时先清空其他）；首个创建的配置自动成为默认。

模型文件 `app/models/feishu_config.py`（仿 `feishu_token.py` 风格）。

## 4. 服务层

`app/services/feishu/config_service.py`（新）：

```python
class FeishuConfigService:
    @staticmethod async def get_default(db) -> FeishuConfig | None
        # is_default=true 优先；无则第一条；无则 None

    @staticmethod async def list_all(db) -> list[FeishuConfig]
    @staticmethod async def create(db, name, app_id, app_secret) -> FeishuConfig
        # 第一条 → is_default=true
    @staticmethod async def update(db, config_id, name=None, app_id=None, app_secret=None)
    @staticmethod async def delete(db, config_id) -> None
        # 删除的是默认 → 下一条自动成为默认（按 created_at 最早）
    @staticmethod async def activate(db, config_id) -> None
        # UPDATE 全部 is_default=false → 目标 true（单条 UPDATE 语句，避免竞态）
```

Secret 加解密复用 `crypto.encrypt_token/decrypt_token`，密钥 `derive_token_key(settings.jwt_secret)`。

## 5. FeishuClient 配置加载（核心改造）

**原则：每次调用从 DB 读默认配置（无缓存）**——配置变更即时生效（FeishuService 是进程级单例，长驻 client 不能用构造时快照）。DB 查询 <1ms、飞书流量低，无性能顾虑。

```python
# app/services/feishu/credentials.py（新）
async def get_feishu_credentials() -> tuple[str, str]:
    """返回 (app_id, app_secret)。DB 默认配置优先，.env 回退（兼容现有部署）。"""
    # 独立 AsyncSession（async_session_maker），查 FeishuConfigService.get_default
    # 无 → (settings.feishu_app_id, settings.feishu_app_secret)

# FeishuClient 改造
class FeishuClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout = httpx.Timeout(timeout_seconds)
        # 不再 self.settings = get_settings()

    async def _creds(self) -> tuple[str, str]:
        return await get_feishu_credentials()

    # exchange_code / refresh_access_token / revoke_token 开头:
    #     app_id, app_secret = await self._creds()
    # 其余文档类方法不变（不需要 app 凭据）
```

`oauth.py build_authorize_url(state)` 改为 `build_authorize_url(app_id: str, state: str | None = None)`（app_id 由调用方传入）；`/oauth/start` 改为：

```python
app_id, _ = await get_feishu_credentials()
if not app_id: raise ApiError(503, "FEISHU_NOT_CONFIGURED", "飞书应用未配置")
url = build_authorize_url(app_id, state)
```

## 6. API（app/api/feishu.py 扩展）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/feishu/configs` | 超管 | 列表：id/name/app_id（脱敏前 6 位）/is_default |
| POST | `/api/feishu/configs` | 超管 + CSRF | {name, app_id, app_secret} → 创建（首个自动默认） |
| PUT | `/api/feishu/configs/{id}` | 超管 + CSRF | {name?, app_id?, app_secret?} 局部更新 |
| DELETE | `/api/feishu/configs/{id}` | 超管 + CSRF | 删除；默认被删 → 下一条自动默认 |
| POST | `/api/feishu/configs/{id}/activate` | 超管 + CSRF | 设为默认 |
| GET | `/api/feishu/configs/status` | 登录用户 | {configured: bool, app_id: str|null}（员工端判断"是否可登录"） |

`/oauth/start`、`/oauth/callback`、`DELETE /connection` 改为走 `get_feishu_credentials()`（不再读 settings 凭据）。

请求体用 Pydantic models（`FeishuConfigCreate`/`FeishuConfigUpdate`），校验：name 1-100、app_id 非空、app_secret 非空（create 必须，update 可选）。

## 7. 前端（components/feishu/feishu-connect.tsx）

打开"连接飞书"弹窗（或现有连接区）分两区块：

**超管视图**（`/auth/me` 返回的 role 判断，现有用户信息已有 role）：
1. **填写 API Key 区**：企业名称 + App ID + App Secret 表单（[保存]）；下方已配置列表（名称 / app_id 脱敏 / [设为默认] / [删除]，当前默认标记）
2. **登录飞书账号区**：现有"连接飞书"按钮（OAuth 跳转）+ 已连接状态/断开

**员工视图**：仅登录区（若无默认配置且员工非超管 → 提示"企业尚未配置飞书，请联系管理员"）

## 8. 兼容与降级

- DB 无配置 → 回退 .env（现有部署平滑过渡，超管可在系统内配置后接管）
- `/oauth/start` 两者皆无 → 503 FEISHU_NOT_CONFIGURED（现行为）

## 9. 测试策略

- **service**（unit，tmp DB 或 mock session）：create 首个自动默认；activate 唯一默认；delete 默认后转移；secret 加解密往返
- **API**（auth_db/超管 fixtures）：员工访问 /configs → 403；超管 CRUD 成功；CSRF 校验
- **credentials**：DB 有配置 → 返回 DB 值；无 → 回退 .env（monkeypatch settings）
- **FeishuClient**：_creds 注入 mock → exchange_code 请求体含正确 app_id/app_secret（httpx MockTransport）
- **前端**：tsc 零新增错误；feishu-connect.test.tsx 现有测试保持通过（或同步更新）

## 10. 明确不做（本期）

- 员工端企业选择列表（"先就默认一个企业"）——登录固定用默认配置
- 多企业并行登录/每企业独立 token
- 回调 URL 可配置
