"""对比基准样本：测试与 benchmark 脚本共享（DRY）。"""

SAMPLES: dict[str, dict] = {
    "qa": {
        "description": "普通问答",
        "messages": [
            {"role": "user", "content": "用一句话介绍 PostgreSQL 的流复制（Streaming Replication）。"}
        ],
    },
    "plan": {
        "description": "JSON 规划",
        "messages": [
            {"role": "system", "content": "你是任务规划器。只输出 JSON，不要输出任何其他文字。"},
            {"role": "user", "content": "为'周末杭州两日游'规划 3 个步骤，每个步骤包含 action 和 input。"},
        ],
    },
    "long": {
        "description": "长文生成",
        "messages": [
            {"role": "user", "content": "写一段 500 字左右的关于数据库索引的科普文章。"}
        ],
    },
}
