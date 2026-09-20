// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { installSidebarHide, zeroFirstTrack } from '../src/client/sidebar-hide'

describe('zeroFirstTrack', () => {
  it('zeroes the first track and keeps the rest', () => {
    expect(zeroFirstTrack('260px minmax(0, 1fr) 0px')).toBe('0px minmax(0, 1fr) 0px')
  })
  it('returns null for values it cannot parse', () => {
    expect(zeroFirstTrack('')).toBeNull()
    expect(zeroFirstTrack('none')).toBeNull()
  })
  it('keeps the center track flexible when the source is a used-px list', () => {
    expect(zeroFirstTrack('280px 1290px 0px')).toBe('0px minmax(0, 1fr) 0px')
  })
  it('preserves an open details track while flexing the center', () => {
    expect(zeroFirstTrack('280px 970px 320px')).toBe('0px minmax(0, 1fr) 320px')
  })
})

describe('installSidebarHide', () => {
  it('injects a zero-width rule for the native sidebar column and cleans up', () => {
    const dispose = installSidebarHide()
    const style = document.getElementById('naoker-nav-hide')
    expect(style?.textContent).toContain('width: 0 !important')
    expect(style?.textContent).toContain('overflow: hidden !important')
    dispose()
    expect(document.getElementById('naoker-nav-hide')).toBeNull()
  })

  it('zeroes the frame grid track when a column exists and restores on dispose', () => {
    const frame = document.createElement('div')
    frame.style.gridTemplateColumns = '260px minmax(0, 1fr) 0px'
    const column = document.createElement('div')
    column.className = 'pI_x6G_sidebarCol'
    frame.appendChild(column)
    document.body.appendChild(frame)
    const dispose = installSidebarHide()
    expect(frame.style.gridTemplateColumns).toBe('0px minmax(0, 1fr) 0px')
    dispose()
    expect(frame.style.gridTemplateColumns).toBe('260px minmax(0, 1fr) 0px')
    frame.remove()
  })

  it('preserves a details track written after install', async () => {
    const frame = document.createElement('div')
    frame.style.gridTemplateColumns = '280px minmax(0, 1fr) 0px'
    const column = document.createElement('div')
    column.className = 'pI_x6G_sidebarCol'
    frame.appendChild(column)
    document.body.appendChild(frame)
    const dispose = installSidebarHide()
    frame.style.gridTemplateColumns = '280px minmax(0, 1fr) 360px'
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(frame.style.gridTemplateColumns).toBe('0px minmax(0, 1fr) 360px')
    dispose()
    frame.remove()
  })

  it('applies the grid-track fix when the column mounts after install', async () => {
    const dispose = installSidebarHide()
    const frame = document.createElement('div')
    frame.style.gridTemplateColumns = '260px minmax(0, 1fr) 0px'
    const column = document.createElement('div')
    column.className = 'pI_x6G_sidebarCol'
    frame.appendChild(column)
    document.body.appendChild(frame)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(frame.style.gridTemplateColumns).toBe('0px minmax(0, 1fr) 0px')
    dispose()
    expect(frame.style.gridTemplateColumns).toBe('260px minmax(0, 1fr) 0px')
    frame.remove()
  })
})
