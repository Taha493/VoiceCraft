import { useEffect, useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { Button } from './ui'

type Row = { word: string; say: string }

export function LexiconDialog({ open, onClose, onError }: { open: boolean; onClose: () => void; onError: (m: string) => void }) {
  const [rows, setRows] = useState<Row[]>([])
  const [defaults, setDefaults] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    api.lexicon().then(
      (l) => {
        setRows(Object.entries(l.user).map(([word, say]) => ({ word, say })))
        setDefaults(l.defaults)
      },
      (e) => onError(String(e)),
    )
  }, [open, onError])

  if (!open) return null

  const save = async () => {
    setSaving(true)
    try {
      await api.saveLexicon(Object.fromEntries(rows.filter((r) => r.word.trim() && r.say.trim()).map((r) => [r.word.trim(), r.say.trim()])))
      onClose()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="font-semibold text-ink">Pronunciations</h2>
            <p className="text-xs text-muted">Teach the voice how to say product names and jargon. Applies to every project.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-raised hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </header>
        <div className="flex-1 space-y-2 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-[11px] font-medium tracking-wide text-faint uppercase">
            <span>Written</span>
            <span>Say it like</span>
            <span />
          </div>
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
              {(['word', 'say'] as const).map((k) => (
                <input
                  key={k}
                  value={r[k]}
                  placeholder={k === 'word' ? 'Supabase' : 'Soopa base'}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))}
                  className="h-8 rounded-md border border-line bg-canvas px-2 text-sm text-ink focus:border-accent focus:outline-none"
                />
              ))}
              <button onClick={() => setRows(rows.filter((_, j) => j !== i))} className="rounded-md p-1.5 text-faint hover:bg-st-overrun/10 hover:text-st-overrun" aria-label="Remove">
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => setRows([...rows, { word: '', say: '' }])}>
            Add word
          </Button>
          <details className="pt-2 text-xs text-muted">
            <summary className="cursor-pointer hover:text-ink">Built-in ({Object.keys(defaults).length})</summary>
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
              {Object.entries(defaults).map(([w, s]) => (
                <span key={w}>
                  <span className="text-ink">{w}</span> → {s}
                </span>
              ))}
            </div>
          </details>
        </div>
        <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={saving} onClick={save}>
            Save
          </Button>
        </footer>
      </div>
    </div>
  )
}
