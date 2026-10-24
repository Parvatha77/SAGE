import type { FieldComparison } from "../api/types"

const RESULT_STYLE: Record<string, string> = {
  similar: "text-green-700 bg-green-50",
  differs: "text-red-700 bg-red-50",
  unknown: "text-gray-400 bg-gray-50",
}

export function DiffTable({ comparisons }: { comparisons: FieldComparison[] }) {
  if (!comparisons.length) return <p className="text-sm text-gray-400">No field comparisons available.</p>

  const similar = comparisons.filter(c => c.result === "similar")
  const differs = comparisons.filter(c => c.result === "differs")
  const unknown = comparisons.filter(c => c.result === "unknown")
  const ordered = [...differs, ...similar, ...unknown]

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-1 pr-4 font-medium">Field</th>
            <th className="py-1 pr-4 font-medium">Anchor</th>
            <th className="py-1 pr-4 font-medium">New</th>
            <th className="py-1 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map(fc => (
            <tr key={fc.field_name} className="border-b last:border-0">
              <td className="py-1.5 pr-4 text-gray-600 capitalize">{fc.field_name.replace(/_/g, " ")}</td>
              <td className="py-1.5 pr-4">{fc.anchor_value ?? <span className="text-gray-300">—</span>}</td>
              <td className="py-1.5 pr-4">{fc.new_value ?? <span className="text-gray-300">—</span>}</td>
              <td className="py-1.5">
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${RESULT_STYLE[fc.result]}`}>
                  {fc.result}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
