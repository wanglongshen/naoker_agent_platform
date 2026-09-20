---
name: knowledge-search
description: 'Use when the agent needs industry methodology, ad-delivery rules, platform policies or case data — i.e. anything answered by the platform industry knowledge base via knowledge_search (Douyin e-commerce official docs, campaign playbooks, policy notes, benchmark cases).'
whenToUse: 'Call this skill first whenever the question touches industry methodology, delivery/bidding rules, platform policy, or case data (行业方法论/投放规则/平台政策/案例数据) — retrieve from the knowledge base before answering.'
---

# Industry Knowledge Base

The DSH runtime in this workspace is backed by the enterprise platform, which hosts an ingested industry knowledge base (Douyin e-commerce official methodology, delivery rules, platform policies and case data). For questions in these areas, retrieve from the knowledge base with `knowledge_search` before answering instead of relying on model memory.

## Tool reference

- `knowledge_search(query, top_k=5, library?)` — semantic search over the platform industry knowledge base. `query` is a natural-language question or keyword; `top_k` caps the number of returned chunks (1..20, default 5); `library` optionally restricts the search to one library.
- Libraries: `千川投放`（投放/出价/流量/搜索）、`直播运营`、`短视频与内容`、`商城与商品卡`、`达人与大促`、`行业案例`（分行业案例）、`平台规则`（规则/协议/标准/细则）、`课程与通用`（课程/通用）。
- 选库建议：问合规/准入/处罚 → `平台规则`；问投放与出价 → `千川投放`；问直播玩法 → `直播运营`；问内容/短视频 → `短视频与内容`；问商城/商品卡 → `商城与商品卡`；问达人/大促 → `达人与大促`；问某行业案例 → `行业案例`；不确定时不要传 `library`（跨库检索）。

## Flow

1. Retrieve first: call `knowledge_search` with the user's question — paraphrase it as a complete question rather than a bare keyword.
2. Ground the answer: base claims on the returned `content`; use `section_path` to locate where the rule sits inside the document.
3. Cite the source: every grounded claim carries its `source_url` so the user can verify it.

## Examples

```
knowledge_search(query="抖音千川全域投放的出价策略有哪些？", top_k=5)
→ [{title: "千川全域投放手册", section_path: "投放手册 > 出价策略", content: "...", source_url: "https://example.com/doc/1", score: 0.87}]
```

## Notes

- Always give the `source_url` for anything drawn from the knowledge base; never present retrieved content as uncited model knowledge.
- If `knowledge_search` returns no items (or nothing relevant), say the knowledge base has no match and fall back to `web_search` for public sources — make clear the answer is not from the internal knowledge base.
- Never fabricate `source_url` values: only cite URLs that came back from the tool.
- The tool attaches the per-instance platform token itself — never ask the user for tokens or put platform credentials in the response.
