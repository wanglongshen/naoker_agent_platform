import { afterEach, describe, expect, it, vi } from 'vitest'
import { apply } from '../src/index.ts'

const BASE = 'http://127.0.0.1:8000'
const CONFIG = { platformBase: BASE, userId: 'u-1', platformToken: 'pt-1' }

interface RegisteredTool {
  name: string
  execute: (args: unknown) => Promise<unknown>
}

interface FetchCall {
  url: string
  init: RequestInit
}

function stubFetch(payload: unknown, status = 200): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async () => new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fn)
  return fn
}

function makeCtx() {
  const register = vi.fn()
  const ctx = { tools: { register } } as unknown as { tools: { register: typeof register }; [key: string]: unknown }
  return { ctx, register }
}

function toolsFrom(register: ReturnType<typeof vi.fn>): Record<string, RegisteredTool> {
  const tools: Record<string, RegisteredTool> = {}
  for (const call of register.mock.calls) {
    const def = call[0] as RegisteredTool
    tools[def.name] = def
  }
  return tools
}

function lastCall(fetchFn: ReturnType<typeof vi.fn>): FetchCall {
  const call = fetchFn.mock.calls.at(-1) as [string, RequestInit]
  return { url: call[0], init: call[1] }
}

function expectAuthHeaders(init: RequestInit): void {
  expect(init.headers).toMatchObject({
    'X-Platform-Token': CONFIG.platformToken,
    'X-Dsh-Platform-User': CONFIG.userId,
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apply', () => {
  it('registers exactly the four platform tools', () => {
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    expect(register).toHaveBeenCalledTimes(4)
    const names = register.mock.calls.map((call) => (call[0] as RegisteredTool).name)
    expect(names).toEqual(['platform_search_files', 'platform_read_file', 'platform_get_docs', 'knowledge_search'])
  })

  it('throws at registration time when platformToken is missing', () => {
    const { ctx, register } = makeCtx()
    expect(() => apply(ctx as never, { platformBase: BASE, userId: 'u-1' } as never)).toThrow(/platformToken/)
    expect(register).not.toHaveBeenCalled()
  })

  it('throws at registration time when platformBase is missing', () => {
    const { ctx, register } = makeCtx()
    expect(() => apply(ctx as never, { userId: 'u-1', platformToken: 't' } as never)).toThrow(/platformBase/)
    expect(register).not.toHaveBeenCalled()
  })
})

describe('platform_search_files', () => {
  it('encodes keyword/media_type as query params and carries auth headers on GET without body', async () => {
    const fetchFn = stubFetch({
      data: {
        items: [
          { id: '11111111-1111-1111-1111-111111111111', filename: '品牌方案.md', media_type: 'text/markdown' },
          { id: '22222222-2222-2222-2222-222222222222', filename: '报价.xlsx', media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
        ],
        page: 1,
        page_size: 20,
        total: 2,
      },
    })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_search_files']

    const result = await tool.execute({ query: '品牌 方案', file_type: 'text/markdown' })

    const { url, init } = lastCall(fetchFn)
    // URLSearchParams: space → '+', non-ASCII percent-encoded (RFC 3986)
    expect(url).toBe(`${BASE}/api/files?keyword=%E5%93%81%E7%89%8C+%E6%96%B9%E6%A1%88&media_type=text%2Fmarkdown&page_size=20`)
    expect(url).not.toContain('品牌')
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
    expectAuthHeaders(init)
    expect(result).toEqual({
      items: [
        { file_id: '11111111-1111-1111-1111-111111111111', title: '品牌方案.md', mime: 'text/markdown' },
        { file_id: '22222222-2222-2222-2222-222222222222', title: '报价.xlsx', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
      ],
    })
  })

  it('omits media_type when file_type is absent', async () => {
    const fetchFn = stubFetch({ data: { items: [] } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_search_files']

    await tool.execute({ query: '合同' })

    const { url } = lastCall(fetchFn)
    expect(url).toBe(`${BASE}/api/files?keyword=%E5%90%88%E5%90%8C&page_size=20`)
  })
})

describe('platform_read_file', () => {
  it('URL-encodes the file_id in the preview path and maps text payload to {title, text}', async () => {
    const fileId = 'abc/123 中文+'
    const fetchFn = stubFetch({ data: { type: 'text', content: '正文内容' } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_read_file']

    const result = await tool.execute({ file_id: fileId })

    const { url, init } = lastCall(fetchFn)
    expect(url).toBe(`${BASE}/api/files/${encodeURIComponent(fileId)}/preview`)
    expectAuthHeaders(init)
    expect(result).toEqual({ title: fileId, text: '正文内容' })
  })

  it('maps stream payloads to a download hint', async () => {
    const fetchFn = stubFetch({ data: { type: 'stream', url: '/api/files/abc/download' } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_read_file']

    const result = (await tool.execute({ file_id: 'abc' })) as { text: string }

    expect(result.text).toContain('/api/files/abc/download')
    expectAuthHeaders(lastCall(fetchFn).init)
  })
})

describe('platform_get_docs', () => {
  it('requests /api/feishu/documents with query/take and maps document_id to doc_id', async () => {
    const fetchFn = stubFetch({
      data: { docs: [{ document_id: 'd1', title: '品牌白皮书' }, { doc_id: 'd2', title: '客户清单' }] },
    })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_get_docs']

    const result = await tool.execute({ query: '品牌', take: 5 })

    const { url, init } = lastCall(fetchFn)
    expect(url).toBe(`${BASE}/api/feishu/documents?query=%E5%93%81%E7%89%8C&take=5`)
    expectAuthHeaders(init)
    expect(result).toEqual({
      docs: [
        { doc_id: 'd1', title: '品牌白皮书' },
        { doc_id: 'd2', title: '客户清单' },
      ],
    })
  })

  it('defaults take to 10 and clamps to [1, 50]', async () => {
    const fetchFn = stubFetch({ data: { docs: [] } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['platform_get_docs']

    await tool.execute({})
    expect(lastCall(fetchFn).url).toBe(`${BASE}/api/feishu/documents?take=10`)

    await tool.execute({ take: 999 })
    expect(lastCall(fetchFn).url).toBe(`${BASE}/api/feishu/documents?take=50`)
  })
})

describe('knowledge_search', () => {
  it('POSTs query/top_k to /api/rag/search with auth headers and maps hits with sources', async () => {
    const fetchFn = stubFetch({
      data: {
        items: [
          {
            chunk_id: 'c-1',
            doc_id: 'd-1',
            title: '千川全域投放手册',
            section_path: '投放手册 > 出价策略',
            content: '出价策略正文',
            source_url: 'https://example.com/doc/1',
            publisher: '抖音电商官方学习中心',
            score: 0.87,
          },
        ],
        elapsed_ms: 12.5,
      },
    })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['knowledge_search']

    const result = await tool.execute({ query: '投放策略', top_k: 3 })

    const { url, init } = lastCall(fetchFn)
    expect(url).toContain('/api/rag/search')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ query: '投放策略', top_k: 3 })
    expectAuthHeaders(init)
    expect(result).toEqual({
      items: [
        {
          title: '千川全域投放手册',
          section_path: '投放手册 > 出价策略',
          content: '出价策略正文',
          source_url: 'https://example.com/doc/1',
          score: 0.87,
        },
      ],
    })
  })

  it('defaults top_k to 5 and clamps to [1, 20]', async () => {
    const fetchFn = stubFetch({ data: { items: [] } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG)
    const tool = toolsFrom(register)['knowledge_search']

    await tool.execute({ query: '平台政策' })
    expect(JSON.parse(String(lastCall(fetchFn).init.body))).toEqual({ query: '平台政策', top_k: 5 })

    await tool.execute({ query: '平台政策', top_k: 999 })
    expect(JSON.parse(String(lastCall(fetchFn).init.body))).toEqual({ query: '平台政策', top_k: 20 })
  })

  it('forwards the library filter to /api/rag/search', async () => {
    const fetchFn = stubFetch({ data: { items: [] } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG as never)
    const tools = toolsFrom(register)

    await tools.knowledge_search.execute({
      query: '平台规则对发货时效的要求',
      top_k: 5,
      library: '平台规则',
    })

    const { init } = lastCall(fetchFn)
    expect(JSON.parse(String(init.body))).toMatchObject({
      query: '平台规则对发货时效的要求',
      top_k: 5,
      library: '平台规则',
    })
  })
})
