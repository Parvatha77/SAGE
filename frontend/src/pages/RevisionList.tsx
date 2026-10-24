import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { getRevisionItems } from "../api/client"

export function RevisionList() {
  const items = useQuery({ queryKey: ["revision-items"], queryFn: getRevisionItems })

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-gray-800">Revision items</h1>
      {items.isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {items.isError && <p className="text-sm text-red-500">Failed to load.</p>}
      {items.data?.length === 0 && <p className="text-sm text-gray-400">No revision items yet.</p>}
      {items.data && items.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="py-2 pr-4 font-medium">Case</th>
                <th className="py-2 pr-4 font-medium">Paper</th>
                <th className="py-2 pr-4 font-medium">Note</th>
                <th className="py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.data.map(item => (
                <tr key={item.id} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="py-2 pr-4">
                    <Link to={`/cases/${item.case_id}`} className="text-blue-600 hover:underline font-mono text-xs">
                      {item.case_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 text-gray-600 text-xs truncate max-w-xs">
                    {item.paper_id.split("/").pop()}
                  </td>
                  <td className="py-2 pr-4 text-gray-600">{item.note ?? "—"}</td>
                  <td className="py-2 text-gray-400 text-xs whitespace-nowrap">
                    {new Date(item.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
