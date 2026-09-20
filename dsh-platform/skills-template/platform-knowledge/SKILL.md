---
name: platform-knowledge
description: 'Use when the agent needs files or documents from the enterprise platform — searching the file library, reading uploaded file contents, or looking up Feishu docs — i.e. anything answered by platform_search_files, platform_read_file or platform_get_docs.'
whenToUse: 'Call this skill when the user asks about content stored on the platform: brand assets, uploaded documents, attachments, or the Feishu knowledge index.'
---

# Platform Files & Documents

The DSH runtime in this workspace is backed by the enterprise platform. Use the three platform tools for anything stored on the platform instead of local disk when the user refers to platform content.

## Tool reference

- `platform_search_files(query, file_type?)` — keyword-search the platform file library. `query` is a free-text keyword (e.g. a brand name, contract type); optional `file_type` filters by media type (pdf/docx/xlsx/pptx/image/video/audio/json/text). Returns `[{file_id, title, mime}]` — capture the `file_id` for later reads.
- `platform_read_file(file_id)` — fetch one file's content by its `file_id` (from search results). Returns `{title, text}` for text-like files; streamed media (video/audio/image/pdf) or unsupported types come back as references or an unsupported marker instead of `text`.
- `platform_get_docs(query?, take=10)` — list/search the Feishu document index. `query` filters by matching text; `take` controls page size (1..50). Returns `[{doc_id, title}]`.

## Flow

1. Search first: `platform_search_files` with the user's keyword to find candidates.
2. Read to confirm: pick the best `file_id`, then `platform_read_file` for the actual content.
3. For Feishu docs (meeting notes, project docs): `platform_get_docs` to index, then read what you found.

## Examples

```
platform_search_files(query="年度合同", file_type="pdf")
→ [{file_id: "f-101", title: "2026-03-12_年度框架合同.pdf", mime: "application/pdf"}]

platform_read_file(file_id="f-101")
→ {title: "2026-03-12_年度框架合同.pdf", text: "..."}

platform_get_docs(query="季度复盘", take=5)
→ [{doc_id: "d-88", title: "Q2 复盘纪要"}]
```

## Notes

- Always carry the `file_id` from search into read; a `file_id` from a stale search may no longer resolve.
- The tools call the platform with the per-instance token already attached — never ask the user for tokens or put platform credentials in the response.
- If a search returns nothing, try a broader keyword or omit `file_type` before reporting failure.
