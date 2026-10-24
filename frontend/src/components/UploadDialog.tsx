import { useRef, useState, type DragEvent } from 'react'
import { FileText, Film, X } from 'lucide-react'
import { Button, Toggle } from './ui'

const CAPTION_EXT = '.srt,.vtt,.json,.txt'

function size(bytes: number) {
  return bytes > 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${(bytes / 1e6).toFixed(1)} MB`
}

interface Props {
  video: File
  onCancel: () => void
  onStart: (opts: { hasCaptions: boolean; captionsFile: File | null }) => void
}

/** Asks whether the video already shows captions; if not, a caption file or script is required. */
export function UploadDialog({ video, onCancel, onStart }: Props) {
  const [hasCaptions, setHasCaptions] = useState(true)
  const [captionsFile, setCaptionsFile] = useState<File | null>(null)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const ready = hasCaptions || !!captionsFile

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) setCaptionsFile(f)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onCancel}>
      <div className="w-full max-w-md rounded-2xl border border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()} onDragOver={(e) => e.stopPropagation()} onDrop={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-semibold text-ink">New video</h2>
          <button onClick={onCancel} className="rounded-lg p-1.5 text-muted hover:bg-raised hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </header>

        <div className="space-y-5 px-5 py-4">
          <div className="flex items-center gap-3 rounded-lg border border-line bg-raised/50 p-3">
            <Film className="size-5 shrink-0 text-accent" />
            <div className="min-w-0">
              <p className="truncate text-sm text-ink">{video.name}</p>
              <p className="text-xs text-muted">{size(video.size)}</p>
            </div>
          </div>

          <Toggle
            checked={hasCaptions}
            onChange={setHasCaptions}
            label="This video already shows captions"
            hint={hasCaptions ? 'VoiceCraft reads the captions on screen and times the voice to them.' : 'No captions on screen. Add a caption file or script for the voice to read.'}
          />

          {!hasCaptions && (
            <div className="space-y-2">
              <div
                onClick={() => input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  setOver(true)
                }}
                onDragLeave={() => setOver(false)}
                onDrop={onDrop}
                className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
                  over ? 'border-accent bg-accent-soft' : captionsFile ? 'border-st-fits/50 bg-st-fits/5' : 'border-line-strong hover:border-accent'
                }`}
              >
                <FileText className={`size-6 ${captionsFile ? 'text-st-fits' : 'text-accent'}`} />
                {captionsFile ? (
                  <>
                    <span className="text-sm text-ink">{captionsFile.name}</span>
                    <span className="text-xs text-muted">Click to choose a different file</span>
                  </>
                ) : (
                  <>
                    <span className="text-sm text-ink">Choose a caption file or script</span>
                    <span className="text-xs text-muted">.srt, .vtt or .json with timings, or a .txt script</span>
                  </>
                )}
              </div>
              <p className="text-[11px] leading-relaxed text-faint">
                A .txt script has one line per caption. Without timings, VoiceCraft spreads the lines across the video based on how long each takes to say.
              </p>
              <input
                ref={input}
                type="file"
                accept={CAPTION_EXT}
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) setCaptionsFile(f)
                }}
              />
            </div>
          )}
        </div>

        <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!ready} onClick={() => onStart({ hasCaptions, captionsFile: hasCaptions ? null : captionsFile })}>
            Start
          </Button>
        </footer>
      </div>
    </div>
  )
}
