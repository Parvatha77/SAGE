const COLORS: Record<string, string> = {
  similar: "bg-green-500",
  differs: "bg-red-400",
  unknown: "bg-gray-300",
  stronger: "bg-green-500",
  weaker: "bg-orange-400",
  none: "bg-green-500",
  low: "bg-yellow-400",
  high: "bg-red-500",
}

export function Meter({ label, value }: { label: string; value: string }) {
  const color = COLORS[value] ?? "bg-gray-300"
  const display = value === "unknown" ? "Unknown" : value.charAt(0).toUpperCase() + value.slice(1)
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-gray-500">{label}</span>
      <div className="flex items-center gap-2">
        <div className={`h-2 w-16 rounded-full ${color}`} />
        <span className="text-sm font-medium">{display}</span>
      </div>
    </div>
  )
}
