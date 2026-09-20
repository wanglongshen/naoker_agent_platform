# 知识库多库拆分 — 验收清单与实测结果

- 日期：2026-09-17
- 设计：`docs/superpowers/specs/2026-09-17-knowledge-library-split-design.md`
- 计划：`docs/superpowers/plans/2026-09-17-knowledge-library-split.md`
- 分配报告（逐篇可审计）：`docs/rag-eval/library-assignment.md`

## 1. 8 个库与最终入库量（实测）

| 库名 | 路由命中（篇） | **已入库（篇）** | 已入库块数 |
| --- | --- | --- | --- |
| 平台规则 | 254 | 225 | 3,457 |
| 千川投放 | 80 | 67 | 737 |
| 达人与大促 | 65 | 53 | 587 |
| 行业案例 | 57 | 52 | 80 |
| 课程与通用 | 62 | 45 | 429 |
| 商城与商品卡 | 37 | 26 | 332 |
| 短视频与内容 | 25 | 20 | 129 |
| 直播运营 | 21 | 14 | 71 |
| **合计** | **601** | **502** | **5,822** |

> 差异原因见第 2 节：97 篇素材解析后**无正文**（视频课/一图读懂类，正文为 0 字符），按规则跳过，不写空文档。

## 2. 素材覆盖核算（按 sha256，非按标题）

| 口径 | 数量 | 说明 |
| --- | --- | --- |
| 采集清单条目 | 601 篇 | manifest.json |
| 去重后内容（sha256） | 599 个 | 3 篇「口碑分」素材内容完全相同，共 1 个 sha256 |
| 解析后无正文（按设计跳过） | 97 篇 | 视频课/纯图卡片，正文为空 |
| **有正文但未入库** | **0 篇** | ✅ 全部入库 |
| 库中实际文档 | 502 篇 | 599 - 97 = 502 ✅ 完全对齐 |

## 3. 迁移（Task 2）验证

- `alembic upgrade head`：`f3a1c7d9e2b4 -> a4b8c2d6e9f1 split rag libraries into eight routed libraries`
- 迁移后：8 库全部存在、老库「行业知识库」已删除、192 篇存量文档按规则重新归属（千川投放 53 / 行业案例 52 / 达人与大促 34 / 课程与通用 20 / 商城与商品卡 18 / 短视频与内容 8 / 直播运营 7 / 平台规则 0），无孤儿文档
- 可逆验证：`alembic downgrade -1` 后老库重现、文档全部指回；再次 `upgrade head` 无报错且结果一致
- 迁移测试：`tests/test_rag_library_split_migration.py` 4 passed

## 4. 检索验证（按库名，真实服务）

| 问题 | 指定库 | 命中 | 耗时 |
| --- | --- | --- | --- |
| 千川全域投放的出价策略有哪些？ | 千川投放 | 3 条（全部来自千川投放库，score 0.75~0.80） | 36.4s（首次冷启动加载向量）/ 后续 52~90ms |
| 商家发货时效和违规处罚的规则是什么？ | 平台规则 | 3 条（平台规则库） | 84.7ms |
| 直播间流量获取的玩法 | 直播运营 | 3 条（直播运营库） | 52.4ms |
| 生鲜商家的经营案例 | 行业案例 | 3 条（行业案例库） | 90.4ms |

命中项均带 `library_name` 与 `source_url`（`school.jinritemai.com` 官方来源）。

## 5. 验收过程中发现并修复的两个真问题

1. **切分器丢弃微内容**（`fix(rag): 切分器兜底` `a48f66f`）：正文非空但只含标题的「一图读懂/一页纸」类素材（11 篇）被 `chunk_markdown` 判为 0 块 → 静默丢弃。修复：正文非空但 0 块时退化为「整篇一个 chunk」（按 `size + overlap` 截断），并补 2 条测试。修复后 11 篇中 9 篇入库，另 2 篇经核实与已入库文档 **sha256 相同**（同内容不同标题），按幂等规则跳过（正确行为）。
2. **测试基线 21 条失败（端口切换遗留）**：本机端口从 3000/8000 切到 3001/8010 后，15 个测试文件里硬编码的 `TEST_ORIGIN = http://localhost:3000` 不再在 `CORS_ORIGINS` 白名单内 → CSRF 校验 403 → 21 条 API 测试失败（与本次拆分无关，属端口切换的连带影响）。修复：`backend/.env` 与 `.env.example` 的 `CORS_ORIGINS` 同时允许 `http://localhost:3001,http://localhost:3000`。修复后 rag 域 **136 passed**。

## 6. 测试结果

| 层 | 命令 | 结果 |
| --- | --- | --- |
| 归类器 | `pytest tests/test_rag_library_routing.py` | 8 passed（含 601 篇分布精确断言） |
| 迁移 | `pytest tests/test_rag_library_split_migration.py` | 4 passed |
| 路由导入 | `pytest tests/test_rag_split_import.py tests/test_rag_ingest_worker.py` | 7 passed |
| 报告 | `pytest tests/test_rag_library_report.py` | 2 passed |
| rag 全域 | `pytest tests/ -k rag -q` | **136 passed** |
| 前端知识库组件 | `npx vitest run src/components/knowledge` | **15 passed** |
| DSH connector | `pnpm test`（server-connector） | 26 passed |

## 7. 浏览器验收清单（待用户确认）

- [ ] 「知识库管理」页显示 **8 张库卡片**，篇数与第 1 节表格一致，按篇数降序
- [ ] 老库「行业知识库」不再出现
- [ ] 进入「平台规则」库 → 数据集列表有 225 篇、可查看切块预览
- [ ] 「搜索测试」页指定「平台规则」库检索「发货时效」有命中
- [ ] Agent 工作台问「平台规则里对商家发货时效的要求是什么？」→ 命中平台规则库并带 `source_url`
- [ ] 「分配报告」`docs/rag-eval/library-assignment.md` 可逐篇核对归属与命中规则

## 8. 已知边界

- 97 篇无正文素材（视频课/纯图卡片）未入库：正文为 0 字符，需浏览器自动化或人工转录才能补齐，属二期范围。
- 平台规则库占 5,822 块中的 3,457 块（59%）：默认全库检索的噪声影响待二期评测集验证（spec §8 已记录触发条件）。
- 首次检索有约 36 秒冷启动（向量缓存加载 5,822 块），后续查询 50~90ms。
