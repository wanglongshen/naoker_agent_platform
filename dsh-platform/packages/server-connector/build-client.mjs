// build-client.mjs —— 把 src/client/index.ts 打成 DSH client 插件信封
import { build } from 'esbuild'
import { mkdirSync, writeFileSync } from 'node:fs'

const EXTERNAL = [
  'react', 'react/jsx-runtime',
  '@deepseek-ai/*',
]

mkdirSync('lib', { recursive: true })
const result = await build({
  entryPoints: ['src/client/index.ts'],
  bundle: true,
  format: 'cjs',
  platform: 'browser',
  target: 'es2022',
  write: false,
  external: EXTERNAL,
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
})

const body = result.outputFiles[0].text
const wrapped = [
  'window.__ModuleLoader__.load({',
  "  id: '@naoker/dsh-platform-connector',",
  '  factory: (require) => {',
  '    var module = { exports: {} }; var exports = module.exports;',
  body,
  '    return module.exports;',
  '  },',
  '});',
  '',
].join('\n')
writeFileSync('lib/client.js', wrapped)
console.log('lib/client.js written')
