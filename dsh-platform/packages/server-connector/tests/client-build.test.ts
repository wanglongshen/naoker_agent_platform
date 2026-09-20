import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('client bundle envelope', () => {
  it('builds lib/client.js wrapped in the dsh module loader envelope', () => {
    execSync('node build-client.mjs', { cwd: process.cwd(), stdio: 'pipe' })
    const out = readFileSync('lib/client.js', 'utf8')
    expect(out).toContain("window.__ModuleLoader__.load({")
    expect(out).toContain("id: '@naoker/dsh-platform-connector'")
    expect(out).toContain('factory: (require) =>')
  })
})
