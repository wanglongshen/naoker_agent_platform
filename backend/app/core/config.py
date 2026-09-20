from functools import lru_cache
from pathlib import Path
import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    test_database_url: str = ""
    jwt_secret: str
    jwt_expire_minutes: int = 43200
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:3001"
    initial_admin_username: str = "admin"
    initial_admin_password: str

    worker_concurrency: int = 3
    worker_poll_interval_seconds: float = 1.0
    worker_lease_seconds: int = 60
    worker_shutdown_grace_seconds: int = 30
    http_timeout_seconds: float = 25.0
    step_timeout_seconds: float = 30.0
    run_timeout_seconds: float = 600.0
    workflow_docs_enabled: bool = True
    workflow_core_doc_path: str = "00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md"
    workflow_blueprint_full_limit: int = 20000  # 核心蓝图全文加载上限（蓝图 15342 字符，须大于此）
    workflow_route_rules: str = (
        "矩阵号;;代运营;;年度运营;;品牌官号;;创始人IP=>00_Agent规范与模板/脑壳儿_矩阵号代运营方案输出规范.md"
        "|评分;;自评;;打分;;复评;;方案质量评估=>00_Agent规范与模板/脑壳儿_方案评分规范.md"
        "|UGC;;种草;;KOC;;素人;;双平台;;季度投放=>00_Agent规范与模板/脑壳儿_UGC种草方案输出规范.md"
        "|调研;;研究=>00_Agent规范与模板/脑壳儿_中国市场调研资料源规范.md"
    )
    fast_path_enabled: bool = True
    merged_plan_thought_enabled: bool = True
    langgraph_enabled: bool = True
    admission_ask_enabled: bool = True  # A1：方案类目标缺 ≥2 项关键约束时先追问（False=回退旧行为）
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 30.0
    max_retry_attempts: int = 3
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    tavily_api_key: str | None = None
    tavily_base_url: str = "https://api.tavily.com"
    agent_storage_root: str = "./var/agent"
    agent_attachment_max_bytes: int = 20_000_000
    agent_attachment_max_count: int = 10
    agent_attachment_retention_days: int = 90  # 附件跟随会话长期保留，retention 仅兜底清孤儿
    agent_run_retention_days: int = 180

    agent_answer_delta_flush_characters: int = 8
    agent_answer_delta_flush_seconds: float = 0.016

    redis_url: str = "redis://localhost:6379/0"
    agent_redis_pubsub_enabled: bool = True
    agent_redis_streams_enabled: bool = False
    agent_redis_batch_window_ms: int = 32
    agent_redis_batch_max_size: int = 20
    agent_sync_persist_events: bool = False

    web_renderer_url: str = "http://127.0.0.1:9001"
    web_renderer_timeout_seconds: float = 40.0
    web_renderer_search_timeout_seconds: float = 60.0
    web_renderer_headless: bool = False
    web_renderer_channel: str | None = None
    # 仅本地开发/差分录制用：允许 web 工具访问非公网解析地址（如 Clash fake-IP 198.18.0.0/15）。
    # 生产必须保持 False（SSRF 防线）。
    web_tool_allow_non_global_targets: bool = False

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_redirect_uri: str = "http://localhost:3000/api/feishu/oauth/callback"
    feishu_token_encryption_key: str = ""

    points_tokens_per_point: int = 10000
    points_initial_grant: int = 1000
    task_chain_flat_points: int = 20  # 任务链缺少 usage 数据时的任务级粗粒度计费（设计允许的降级口径）

    quality_module_min_chars: int = 200
    quality_review_max_rounds: int = 2
    quality_hollow_phrases: str = "本方案将全面赋能,根据实际情况进行调整,助力,赋能,众所周知,综上所述"

    # RAG embedding 供给：local=sentence-transformers 本地模型；http=OpenAI 兼容 /embeddings
    rag_embedding_provider: str = "local"
    rag_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rag_embedding_dim: int = 512
    rag_embedding_base_url: str = ""
    rag_embedding_api_key: str = ""
    rag_warmup_on_startup: bool = True  # 启动后台预热 embedding 模型与向量矩阵（D4）

    dsh_home_root: str = "var/dsh"
    dsh_port_min: int = 3100
    dsh_port_max: int = 3399
    dsh_idle_seconds: int = 600
    dsh_stop_grace_seconds: int = 30
    dsh_health_timeout_seconds: int = 30
    dsh_instance_mode: str = "dev_bin"  # dev_bin=直接用全局 dsh 调试；vendored=deepseek-harness 构建产物（线上）
    dsh_platform_token_ttl_seconds: int = 300
    dsh_trusted_hosts: str = "localhost:8010"
    dsh_skills_dir: str = "skills"  # home 内相对路径
    dsh_platform_base: str = "http://127.0.0.1:8010"  # connector 插件调用平台 API 的基地址
    dsh_task_timeout_seconds: float = 300.0  # 任务链单个 DSH headless 子任务墙钟上限

    @field_validator("dsh_instance_mode")
    @classmethod
    def validate_dsh_instance_mode(cls, v: str) -> str:
        if v not in ("dev_bin", "vendored"):
            raise ValueError("dsh_instance_mode 只允许 dev_bin|vendored")
        return v

    @property
    def dsh_home_root_path(self) -> Path:
        """DSH home 根目录的绝对路径。

        相对值锚定到 backend/ 目录（与实例管理器的文件操作语义一致）；子进程以
        repo_root 为 cwd，若把相对路径直接塞进 DSH_HOME，子进程会解析到 repo 根
        下的另一个 home（配置/插件都在 backend/var/dsh，导致实例加载不到插件）。
        """
        root = Path(self.dsh_home_root)
        return root if root.is_absolute() else (BACKEND_ROOT / root).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_browser_channel(settings: Settings | None = None) -> str | None:
    """Resolve browser channel: explicit setting wins; on Windows default to msedge, else None (bundled chromium)."""
    s = settings or Settings()
    if s.web_renderer_channel:
        return s.web_renderer_channel
    if sys.platform == "win32":
        return "msedge"
    return None
