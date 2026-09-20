# 前端导航体验优化设计

日期：2026-08-05
状态：已批准

## 背景与目标

系统前端在 dev 模式下每次进入新页面都会出现 "Compiling..." → "Rendering..." 提示与等待——Next.js webpack 按需编译的行为。Turbopack 已知与本项目存在兼容问题（`dev` 脚本刻意使用 `--webpack`），排除切换。目标：通过**路由预热**（dev 场景）与**生产模式脚本**（使用场景）消除感知到的编译等待，不改构建引擎。

## 方案一：路由预热脚本

新增 `frontend/scripts/prewarm-routes.mjs`（Node 脚本，无第三方依赖，用内置 fetch——Node 18+ 可用）：

- 执行流程：轮询 `http://localhost:3000/agent`（每 1s，最多 60 次）直到返回响应（dev 服务器就绪）→ 顺序 GET 预热路由清单 → 每个路由等待响应完成（触发 Next 按需编译，此时才真正完成 route 编译）→ 全部完成后打印每路由的状态码与耗时总结
- 路由清单（以 `frontend/src/app` 实际存在的路由为准，实现时列出）：`/login`、`/agent`、`/files`、`/files/admin`（若存在）、`/users`、`/roles`、`/settings/profile`、`/audit`（若存在）
- 未登录访问会 302 跳转或渲染守卫——不影响编译触发，非 200 响应也视为已编译，继续下一个
- `package.json` 新增 `"prewarm": "node scripts/prewarm-routes.mjs"`（不并入 `dev` 脚本，避免阻塞启动与 shell 兼容问题）
- 用法：终端 1 `npm run dev` 就绪后，终端 2 执行 `npm run prewarm`——dev 生命周期内路由编译缓存生效，仅需执行一次；每次重启 dev 服务器后重新执行

## 方案二：生产模式脚本

- `package.json` 新增 `"serve": "next build && next start"`——一条命令完成生产构建并启动（路由预构建、无按需编译、无 Compiling/Rendering）
- 保持 webpack（不引入 Turbopack）；前端 API 地址配置与 dev 一致（NEXT_PUBLIC_API_BASE_URL 或既有代理），不新增配置
- 日常使用场景建议用 `npm run serve`；开发场景仍用 `npm run dev`

## 方案三：README 文档

README 前端章节补两段傻瓜式说明：
1. 路由预热：`npm run dev` 启动后执行 `npm run prewarm`，首次访问页面不再有编译等待
2. 生产模式：`npm run serve`（构建 + 启动），体验最佳；每次改代码后需重新执行

## 验证

- 冒烟：dev 服务器就绪后执行 `npm run prewarm`，全部路由返回状态码（200/302 等）且有响应耗时记录；第二次访问浏览器页面无 Compiling 提示
- 冒烟：`npm run serve` 构建成功、`next start` 后首页可访问
- 不写单元测试（Node 运维脚本，冒烟验证为准）
