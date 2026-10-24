import type { SegmentStatus } from '../api'

export const segmentStatus: Record<SegmentStatus, { label: string; color: string; bg: string; hint: string }> = {
  fits: { label: 'Fits', color: 'text-st-fits', bg: 'bg-st-fits', hint: 'Finishes while its caption is on screen.' },
  borrowed: { label: 'Uses gap', color: 'text-st-borrowed', bg: 'bg-st-borrowed', hint: 'Runs into the pause before the next caption.' },
  sped_up: { label: 'Sped up', color: 'text-st-sped', bg: 'bg-st-sped', hint: 'Regenerated slightly faster (at most 1.12×) to fit.' },
  held: { label: 'Frame held', color: 'text-st-held', bg: 'bg-st-held', hint: 'The video pauses on the caption so the line can finish.' },
  overrun: { label: 'Overruns', color: 'text-st-overrun', bg: 'bg-st-overrun', hint: 'Too long for its slot; shorten the caption or allow frame holds.' },
}
