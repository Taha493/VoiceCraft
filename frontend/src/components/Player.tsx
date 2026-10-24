import { forwardRef, useImperativeHandle, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface PlayerHandle {
  seek: (t: number) => void
  play: () => void
}

interface Props {
  src: string
  aspect: number
  region: Box | null
  guides?: Box[]
  editingRegion: boolean
  onRegionChange: (b: Box) => void
  onTime: (t: number) => void
}

type Drag = { mode: 'move' | 'draw' | 'n' | 's'; startX: number; startY: number; orig: Box }

const clamp = (v: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v))

/** Video with an optional caption-region overlay that can be moved, redrawn and resized. */
export const Player = forwardRef<PlayerHandle, Props>(function Player({ src, aspect, region, guides = [], editingRegion, onRegionChange, onTime }, ref) {
  const video = useRef<HTMLVideoElement>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)

  useImperativeHandle(ref, () => ({
    seek: (t) => {
      if (video.current) video.current.currentTime = t
    },
    play: () => void video.current?.play(),
  }))

  const point = (e: ReactPointerEvent) => {
    const r = overlay.current!.getBoundingClientRect()
    return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) }
  }

  const onDown = (e: ReactPointerEvent, mode: Drag['mode']) => {
    e.stopPropagation()
    e.preventDefault()
    const p = point(e)
    overlay.current!.setPointerCapture(e.pointerId)
    const orig = region ?? { x: 0, y: p.y, w: 1, h: 0.02 }
    setDrag({ mode, startX: p.x, startY: p.y, orig })
    if (mode === 'draw') onRegionChange({ x: p.x, y: p.y, w: 0.01, h: 0.01 })
  }

  const onMove = (e: ReactPointerEvent) => {
    if (!drag) return
    const p = point(e)
    const { orig } = drag
    if (drag.mode === 'move') {
      onRegionChange({ ...orig, x: clamp(orig.x + p.x - drag.startX, 0, 1 - orig.w), y: clamp(orig.y + p.y - drag.startY, 0, 1 - orig.h) })
    } else if (drag.mode === 'draw') {
      const x0 = Math.min(drag.startX, p.x)
      const y0 = Math.min(drag.startY, p.y)
      onRegionChange({ x: x0, y: y0, w: Math.max(0.02, Math.abs(p.x - drag.startX)), h: Math.max(0.02, Math.abs(p.y - drag.startY)) })
    } else if (drag.mode === 'n') {
      const y = clamp(p.y, 0, orig.y + orig.h - 0.03)
      onRegionChange({ ...orig, y, h: orig.y + orig.h - y })
    } else {
      onRegionChange({ ...orig, h: clamp(p.y - orig.y, 0.03, 1 - orig.y) })
    }
  }

  return (
    <div className="relative mx-auto overflow-hidden rounded-xl bg-black ring-1 ring-line" style={{ aspectRatio: aspect, width: `min(100%, calc(52vh * ${aspect}))` }}>
      <video
        ref={video}
        src={src}
        className="size-full"
        controls={!editingRegion}
        playsInline
        preload="metadata"
        onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
        onSeeked={(e) => onTime(e.currentTarget.currentTime)}
      />
      {region && (
        <div
          ref={overlay}
          className={`absolute inset-0 ${editingRegion ? 'cursor-crosshair bg-black/45' : 'pointer-events-none'}`}
          onPointerDown={editingRegion ? (e) => onDown(e, 'draw') : undefined}
          onPointerMove={onMove}
          onPointerUp={() => setDrag(null)}
        >
          {guides.map((g, i) => (
            <div
              key={i}
              className="pointer-events-none absolute rounded-md border border-dashed border-white/50"
              style={{ left: `${g.x * 100}%`, top: `${g.y * 100}%`, width: `${g.w * 100}%`, height: `${g.h * 100}%` }}
            >
              <span className="absolute -top-5 right-2 text-[10px] text-white/70">detected band {i + 1}</span>
            </div>
          ))}
          <div
            className={`absolute rounded-md border-2 ${editingRegion ? 'cursor-move border-accent bg-accent/10 shadow-[0_0_0_9999px_rgba(0,0,0,0.25)]' : 'border-dashed border-accent/0'}`}
            style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.w * 100}%`, height: `${region.h * 100}%` }}
            onPointerDown={editingRegion ? (e) => onDown(e, 'move') : undefined}
          >
            {editingRegion && (
              <>
                <span className="absolute -top-6 left-2 rounded bg-accent-strong px-1.5 py-0.5 text-[10px] font-medium text-white">Caption area</span>
                <span className="absolute -top-1.5 left-1/2 h-3 w-10 -translate-x-1/2 cursor-ns-resize rounded-full bg-accent" onPointerDown={(e) => onDown(e, 'n')} />
                <span className="absolute -bottom-1.5 left-1/2 h-3 w-10 -translate-x-1/2 cursor-ns-resize rounded-full bg-accent" onPointerDown={(e) => onDown(e, 's')} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
})
