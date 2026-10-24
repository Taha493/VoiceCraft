import type { Hold } from '../api'

export function fmtTime(t: number, precise = false): string {
  if (!Number.isFinite(t)) return '--:--'
  const sign = t < 0 ? '-' : ''
  t = Math.abs(t)
  const m = Math.floor(t / 60)
  const s = t - m * 60
  const sec = precise ? s.toFixed(2).padStart(5, '0') : Math.floor(s).toString().padStart(2, '0')
  return `${sign}${m}:${sec}`
}

export function parseTime(text: string): number | null {
  const m = text.trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/)
  if (!m) return null
  return (m[1] ? parseInt(m[1], 10) * 60 : 0) + parseFloat(m[2])
}

/** Narrated output time → source video time (holds freeze the source clock). */
export function outputToVideo(t: number, holds: Hold[]): number {
  let shift = 0
  for (const h of [...holds].sort((a, b) => a.video_time - b.video_time)) {
    const holdStartOut = h.video_time + shift
    if (t < holdStartOut) break
    if (t < holdStartOut + h.duration) return h.video_time
    shift += h.duration
  }
  return t - shift
}

export function videoToOutput(t: number, holds: Hold[]): number {
  return t + holds.filter((h) => h.video_time < t).reduce((sum, h) => sum + h.duration, 0)
}
