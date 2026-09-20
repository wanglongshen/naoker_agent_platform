import type { UserConfig } from 'tsdown'

// Server-only connector: the node-half ESM bundle into lib/index.js.
// DSH resolves the peer runtime deps against the profile tree, so the
// @deepseek-ai/* imports stay external (never bundled).
export default {
  entry: ['src/index.ts'],
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'es2024',
  fixedExtension: false,
  dts: false,
  clean: true,
  external: ['@deepseek-ai/cordis', '@deepseek-ai/dsh-tools', '@deepseek-ai/schemastery'],
} satisfies UserConfig
