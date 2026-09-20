/**
 * DSH 原生侧栏内的稳定触发点（Task 1 spike 源码级考证，证据见 `dsh-platform/NOTES.md` §8）。
 * 选择器一律锚定 `data-slot` / `aria-label` / 官方稳定 class 子串；`data-pane` 分支为皮肤同款
 * 前向兼容臂（0.1.1-rc.2 实测未输出该属性，见 NOTES §8.4）。
 */

/** 侧栏列：AppFrame 的 `.sidebarCol` 网格项（`[class*='sidebarCol']` 实测命中）。 */
export const SIDEBAR_COLUMN_SELECTOR = ":is([data-pane='sidebar'], [class*='sidebarCol'])"

/** 设置触发按钮：`sidebar.settings` 槽锚点（`display:contents`）的直接按钮子元素。 */
export const SETTINGS_TRIGGER_SELECTOR = "[data-slot='sidebar.settings'] > :is(button, [role='button'])"

/** 工作区/会话浏览区：`sidebar.workspaces` 槽锚点。 */
export const WORKSPACE_REGION_SELECTOR = "[data-slot='sidebar.workspaces']"

/** 过滤/排序触发按钮（`IconPersonalizationOutline16`，aria-label = 视图选项/View options）。 */
export const FILTER_TRIGGER_SELECTOR = "[data-slot='sidebar.workspaces'] button[aria-label='视图选项'], [data-slot='sidebar.workspaces'] button[aria-label='View options']"

/** ＋新建工作区触发按钮（`IconProjectAddOutline16`，aria-label = 添加工作区/Add workspace）。 */
export const ADD_WORKSPACE_TRIGGER_SELECTOR = "[data-slot='sidebar.workspaces'] button[aria-label='添加工作区'], [data-slot='sidebar.workspaces'] button[aria-label='Add workspace']"
