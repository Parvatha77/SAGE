import { LABEL_COLOR, LABEL_DISPLAY } from "../api/types"

export function LabelChip({ label }: { label: string }) {
  const cls = LABEL_COLOR[label] ?? "bg-gray-100 text-gray-600"
  const text = LABEL_DISPLAY[label] ?? label
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {text}
    </span>
  )
}
