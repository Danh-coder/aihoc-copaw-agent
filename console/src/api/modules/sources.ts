import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export const sourcesApi = {
  list: () => request<any[]>("/sources/"),
  reindex: (id: number) => request(`/sources/${id}/reindex`, { method: "POST" }),
  query: (q: string, top_k = 5) => request(`/sources/query`, { method: "POST", body: JSON.stringify({ query: q, top_k }) }),

  upload: async (file: File) => {
    const url = getApiUrl(`/sources/upload`);
    const form = new FormData();
    form.append("file", file);

    const headers = buildAuthHeaders();

    const resp = await fetch(url, { method: "POST", headers, body: form });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Upload failed: ${resp.status} ${resp.statusText} - ${txt}`);
    }
    return resp.json();
  },
};
