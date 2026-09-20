/// <reference lib="dom" />
import { SIDEBAR_COLUMN_SELECTOR } from './selectors.ts'

const STYLE_ID = 'naoker-nav-hide'

/**
 * 把 `grid-template-columns` 的第一轨归零，并把中间轨恢复为弹性 `minmax(0, 1fr)`
 * （末轨 = details 面板宽度，原样保留）；无法解析时返回 null。
 *
 * 输入可能是 AppFrame 的内联逻辑值（`280px minmax(0, 1fr) 0px`）或 computed 的
 * 已用像素值（`280px 1290px 0px`）。后者必须显式恢复弹性：只把第一轨置 0 会把
 * 中间轨冻结成当时的像素宽，释放出的侧栏宽度（SIDEBAR_DEFAULT=280）在 frame
 * 右侧留成空白（2026-09-18 真实实例实测，见 dsh-platform/NOTES.md §9）。
 */
export function zeroFirstTrack(value: string): string | null {
  const tracks = value.trim().split(/\s+/)
  if (tracks.length < 3 || tracks[0] === '' || tracks[0] === 'none') return null
  tracks[0] = '0px'
  if (/^\d+(?:\.\d+)?px$/.test(tracks[1])) tracks[1] = 'minmax(0, 1fr)'
  return tracks.join(' ')
}

/**
 * 隐藏原生侧栏（NOTES §8.3）：① 列元素零宽并裁剪（保留整棵 DOM——设置面板是该列的
 * fixed 后代，display:none 会连带隐藏，且 fixed 逃逸 overflow 裁剪）；② AppFrame 的
 * 第一网格轨归零、中间轨恢复 `minmax(0, 1fr)`（关闭态轨宽恒为 56px，仅列零宽会残留
 * 空轨；中间轨不恢复弹性则右侧留白，见 NOTES §9）；③ AppFrame 每次 store 变化都会
 * 重写内联 style，用 MutationObserver 从内联逻辑值重放覆盖（computed 在过渡期间
 * 仍是旧值，不可作重放源）。列内触发点仍可程序化点击。
 *
 * 插件在应用挂载前就会 apply（实测 2026-09-15：列元素尚未出现时只注入 CSS，网格轨
 * 残留 → 界面左侧空出一整列），因此列不存在时先监听 document，出现后再接管网格轨。
 */
export function installSidebarHide(): () => void {
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `
${SIDEBAR_COLUMN_SELECTOR} {
  width: 0 !important;
  min-width: 0 !important;
  flex: 0 0 0 !important;
  overflow: hidden !important;
  border-right: none !important;
}
`
  document.head.appendChild(style)

  let frame: HTMLElement | null = null
  let originalTracks = ''
  let frameObserver: MutationObserver | null = null
  let waitObserver: MutationObserver | null = null

  const replay = (): void => {
    if (!(frame instanceof HTMLElement)) return
    // 优先读内联逻辑值（AppFrame 写的 `${sidebar}px minmax(0, 1fr) ${details}px`）：
    // computed 在轨过渡期间仍是旧宽度，用它重放会撤销合法的轨变化（details
    // 打开/窗口缩放）并把中间轨冻结成像素（见 NOTES §9）。
    const inline = frame.style.gridTemplateColumns
    const zeroed = zeroFirstTrack(inline !== '' ? inline : getComputedStyle(frame).gridTemplateColumns)
    if (zeroed !== null) frame.style.gridTemplateColumns = zeroed
  }

  const attach = (): boolean => {
    const column = document.querySelector(SIDEBAR_COLUMN_SELECTOR)
    if (!(column instanceof HTMLElement)) return false
    const parent = column.parentElement
    if (!(parent instanceof HTMLElement)) return false
    frame = parent
    originalTracks = frame.style.gridTemplateColumns
    replay()
    frameObserver = new MutationObserver(replay)
    frameObserver.observe(frame, { attributes: true, attributeFilter: ['style'] })
    return true
  }

  if (!attach()) {
    waitObserver = new MutationObserver(() => {
      if (attach()) {
        waitObserver?.disconnect()
        waitObserver = null
      }
    })
    waitObserver.observe(document.documentElement, { childList: true, subtree: true })
  }

  return () => {
    style.remove()
    frameObserver?.disconnect()
    waitObserver?.disconnect()
    if (frame instanceof HTMLElement) frame.style.gridTemplateColumns = originalTracks
  }
}
