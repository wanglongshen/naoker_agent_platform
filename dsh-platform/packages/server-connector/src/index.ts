/**
 * @module @naoker/dsh-platform-connector
 *
 * DSH server-side connector for the enterprise platform: registers four
 * model-callable tools that proxy the current user's platform data
 * (file library search/read, Feishu document listing + industry knowledge
 * search). Auth is carried in
 * `X-Platform-Token` / `X-Dsh-Platform-User` request headers; the token never
 * reaches tool outputs.
 *
 * Platform-side contract (backend `app/api/files.py`, `app/api/feishu.py`) is
 * documented in `dsh-platform/NOTES.md` §7; two platform gaps (dual-check auth,
 * Feishu docs index endpoint) are backend follow-ups and are tracked there.
 */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'naoker-platform-connector'
export const inject = ['tools']

/** Connector configuration, delivered via the profile patch row (`cordis.patch.yml` config key). */
export interface Config {
  /** Platform HTTP origin, e.g. `http://127.0.0.1:8000`. */
  platformBase: string
  /** Platform user id (who owns the call; matches `X-Dsh-Platform-User`). */
  userId: string
  /** Short-lived platform-issued token (`X-Platform-Token`). */
  platformToken: string
}

/** Schemastery config schema: missing fields fail loud at plugin load. */
export const Config: z<Config> = z.object({
  platformBase: z.string().required(),
  userId: z.string().required(),
  platformToken: z.string().required(),
})

const CONFIG_FIELDS = ['platformBase', 'userId', 'platformToken'] as const
type ConfigField = (typeof CONFIG_FIELDS)[number]

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function assertConfig(input: Partial<Config>): asserts input is Config {
  for (const field of CONFIG_FIELDS) {
    if (!isNonEmptyString(input[field])) {
      throw new Error(
        `naoker-platform-connector: config.${field} is required — the platform patch row must set platformBase/userId/platformToken before the tools can be registered`,
      )
    }
  }
}

interface PlatformEnvelope {
  readonly data?: unknown
}

/** Extra request options for {@link platformFetch}; the connector auth headers are always added. */
interface PlatformFetchOptions {
  /** HTTP method; defaults to GET. */
  method?: string
  /** JSON request body; attached only when provided so GETs stay body-less. */
  body?: string
  /** Extra headers merged over the connector auth headers. */
  headers?: Record<string, string>
}

/**
 * Fetch one platform API path with the connector's auth headers.
 * Defaults to GET without a body; POST callers pass `method`/`body` explicitly.
 * @param config - validated connector config.
 * @param path - platform-relative path beginning with `/api/...`.
 * @param options - extra request options (method/body/headers).
 * @returns the parsed response envelope (`{data, message, request_id}`).
 */
async function platformFetch(config: Config, path: string, options: PlatformFetchOptions = {}): Promise<PlatformEnvelope> {
  const response = await fetch(`${config.platformBase}${path}`, {
    method: options.method ?? 'GET',
    ...(options.body === undefined ? {} : { body: options.body }),
    headers: {
      'Content-Type': 'application/json',
      'X-Platform-Token': config.platformToken,
      'X-Dsh-Platform-User': config.userId,
      ...(options.headers ?? {}),
    },
  })
  if (!response.ok) {
    const preview = (await response.text().catch(() => '')).slice(0, 200)
    throw new Error(`platform API ${response.status} ${path}: ${preview}`)
  }
  return (await response.json()) as PlatformEnvelope
}

interface SearchFileInput {
  query: string
  file_type?: string
}

interface FileListItem {
  file_id: string
  title: string
  mime: string
}

function mapListItems(files: unknown): FileListItem[] {
  if (!Array.isArray(files)) return []
  return files.map((raw) => {
    const file = raw as { id?: unknown; filename?: unknown; media_type?: unknown }
    return {
      file_id: String(file.id ?? ''),
      title: String(file.filename ?? ''),
      mime: String(file.media_type ?? ''),
    }
  })
}

function buildSearchTool(config: Config) {
  return defineTool({
    name: 'platform_search_files',
    description:
      '搜索当前用户在企业智助平台「文件库」中的资料（品牌方上传的素材、文档、数据文件），按文件名/内容关键词过滤，返回 file_id/title/mime 列表。营销场景触发词：客户资料、品牌素材、上传的文件、合同、报价单、数据表格等。',
    parameters: {
      query: { type: 'string', required: true, description: '搜索关键词（匹配文件名与文本内容）' },
      file_type: { type: 'string', description: '可选 MIME 类型过滤，如 text/markdown、application/json（不传则不限制）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          items: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                file_id: { type: 'string', required: true },
                title: { type: 'string', required: true },
                mime: { type: 'string', required: true },
              },
            },
          },
        },
      },
      render: (_args, value) => {
        const lines = value.items.map((item) => `- ${item.title} (${item.mime}) [${item.file_id}]`)
        return [{ type: 'text', text: value.items.length === 0 ? '未找到匹配的文件。' : `${value.items.length} 个文件：\n${lines.join('\n')}` }]
      },
    },
    async execute(args: SearchFileInput) {
      const query = new URLSearchParams()
      query.set('keyword', args.query)
      if (typeof args.file_type === 'string' && args.file_type.length > 0) {
        query.set('media_type', args.file_type)
      }
      query.set('page_size', '20')
      const body = await platformFetch(config, `/api/files?${query.toString()}`)
      const data = body.data as { items?: unknown }
      return { items: mapListItems(data?.items) }
    },
  })
}

interface ReadFileInput {
  file_id: string
}

function buildReadTool(config: Config) {
  return defineTool({
    name: 'platform_read_file',
    description:
      '读取企业智助平台「文件库」中指定文件的正文内容（支持文本/Markdown/JSON/Word/Excel/PPT 提取；图片/音视频/PDF 返回下载地址）。营销场景触发词：读取文件内容、查看资料正文、这个文件里面写了什么。',
    parameters: {
      file_id: { type: 'string', required: true, description: '文件 ID，由 platform_search_files 的 file_id 返回' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          title: { type: 'string', required: true },
          text: { type: 'string', required: true },
        },
      },
      render: (_args, value) => [{ type: 'text', text: `${value.title}\n\n${value.text}` }],
    },
    async execute(args: ReadFileInput) {
      const body = await platformFetch(config, `/api/files/${encodeURIComponent(args.file_id)}/preview`)
      const data = (body.data ?? {}) as { type?: string; content?: string; url?: string }
      let text: string
      if (data.type === 'text') {
        text = data.content ?? ''
      } else if (data.type === 'stream') {
        text = `该文件为二进制/媒体类型，无法直接转文本；下载地址：${data.url ?? ''}`
      } else {
        text = '该文件类型暂不支持文本预览。'
      }
      // The /preview payload carries no filename; the platform has no per-file
      // metadata GET, so the caller-held file_id stands in for title (NOTES.md §7.4).
      return { title: args.file_id, text }
    },
  })
}

interface GetDocsInput {
  query?: string
  take?: number
}

interface DocListItem {
  doc_id: string
  title: string
}

function mapDocList(docs: unknown): DocListItem[] {
  if (!Array.isArray(docs)) return []
  return docs.map((raw) => {
    const doc = raw as { doc_id?: unknown; document_id?: unknown; title?: unknown }
    return {
      doc_id: String(doc.doc_id ?? doc.document_id ?? ''),
      title: String(doc.title ?? ''),
    }
  })
}

function buildGetDocsTool(config: Config) {
  return defineTool({
    name: 'platform_get_docs',
    description:
      '列出当前用户已连接的飞书文档（需已在平台连接飞书账号），可按关键词过滤，返回 doc_id/title 列表。营销场景触发词：飞书文档、看看我的飞书文件、检索飞书里的品牌资料。',
    parameters: {
      query: { type: 'string', description: '可选关键词过滤' },
      take: { type: 'integer', description: '返回条数，默认 10（上限 50）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          docs: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                doc_id: { type: 'string', required: true },
                title: { type: 'string', required: true },
              },
            },
          },
        },
      },
      render: (_args, value) => {
        const lines = value.docs.map((doc) => `- ${doc.title} [${doc.doc_id}]`)
        return [{ type: 'text', text: value.docs.length === 0 ? '未找到匹配的飞书文档。' : `${value.docs.length} 个飞书文档：\n${lines.join('\n')}` }]
      },
    },
    async execute(args: GetDocsInput) {
      const query = new URLSearchParams()
      if (typeof args.query === 'string' && args.query.length > 0) {
        query.set('query', args.query)
      }
      const take = Math.max(1, Math.min(args.take ?? 10, 50))
      query.set('take', String(take))
      const body = await platformFetch(config, `/api/feishu/documents?${query.toString()}`)
      const data = body.data as { docs?: unknown }
      return { docs: mapDocList(data?.docs) }
    },
  })
}

interface KnowledgeSearchInput {
  query: string
  top_k?: number
  library?: string
}

interface KnowledgeHit {
  title: string
  section_path: string
  content: string
  source_url: string
  score: number
}

function mapKnowledgeHits(items: unknown): KnowledgeHit[] {
  if (!Array.isArray(items)) return []
  return items.map((raw) => {
    const item = raw as {
      title?: unknown
      section_path?: unknown
      content?: unknown
      source_url?: unknown
      score?: unknown
    }
    return {
      title: String(item.title ?? ''),
      section_path: String(item.section_path ?? ''),
      content: String(item.content ?? ''),
      source_url: String(item.source_url ?? ''),
      score: Number(item.score ?? 0),
    }
  })
}

function buildKnowledgeSearchTool(config: Config) {
  return defineTool({
    name: 'knowledge_search',
    description:
      '检索平台「行业知识库」中已入库的官方行业方法论、投放规则、平台政策与案例数据（语义检索，返回带来源引用的原文片段）。营销场景触发词：行业方法论、投放策略、出价规则、平台政策、案例数据、某个玩法怎么做/平台有什么规定。',
    parameters: {
      query: { type: 'string', required: true, description: '检索问题或关键词，用自然语言描述要查的行业知识' },
      top_k: { type: 'integer', description: '返回片段数，默认 5（范围 1-20）' },
      library: {
        type: 'string',
        description:
          '可选：限定知识库名称。可选值：千川投放、直播运营、短视频与内容、商城与商品卡、达人与大促、行业案例、平台规则、课程与通用。不传则跨全部库检索。',
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          items: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                title: { type: 'string', required: true },
                section_path: { type: 'string', required: true },
                content: { type: 'string', required: true },
                source_url: { type: 'string', required: true },
                score: { type: 'number', required: true },
              },
            },
          },
        },
      },
      render: (_args, value) => {
        if (value.items.length === 0) {
          return [{ type: 'text', text: '行业知识库未命中相关片段；如需公开资料可改用 web_search。' }]
        }
        const lines = value.items.map((item) => {
          const path = item.section_path.length > 0 ? ` > ${item.section_path}` : ''
          return `- ${item.title}${path}（相关度 ${item.score.toFixed(3)}）\n  来源：${item.source_url}\n  ${item.content}`
        })
        return [{ type: 'text', text: `${value.items.length} 个知识片段：\n${lines.join('\n')}` }]
      },
    },
    async execute(args: KnowledgeSearchInput) {
      const top_k = Math.max(1, Math.min(args.top_k ?? 5, 20))
      const body = await platformFetch(config, '/api/rag/search', {
        method: 'POST',
        body: JSON.stringify({
          query: args.query,
          top_k,
          ...(typeof args.library === 'string' && args.library.length > 0
            ? { library: args.library }
            : {}),
        }),
      })
      const data = body.data as { items?: unknown }
      return { items: mapKnowledgeHits(data?.items) }
    },
  })
}

/**
 * Register the four platform tools on `ctx.tools`.
 * @param ctx - registrant context carrying the tool registry (`inject = ['tools']`).
 * @param config - platform connector config (patch row config key).
 */
export function apply(ctx: Context, config: Config): void {
  assertConfig(config)
  ctx.tools.register(buildSearchTool(config))
  ctx.tools.register(buildReadTool(config))
  ctx.tools.register(buildGetDocsTool(config))
  ctx.tools.register(buildKnowledgeSearchTool(config))
}
