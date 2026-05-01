import { useState } from "react";
import { Input, Button, message } from "antd";
import { getApiUrl, getApiToken } from "@/api/config";

export default function QueryBox({ onAnswer }: { onAnswer?: (a: any) => void }) {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!q) return message.warning("Enter a query");
    setLoading(true);
    try {
      // prefer /answer endpoint for RAG
      const token = getApiToken();
      const ans = await fetch(getApiUrl("/sources/answer"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ query: q, top_k: 5 }),
      }).then((r) => r.json());
      if (onAnswer) onAnswer(ans);
      message.success("Answer received");
    } catch (err: any) {
      message.error(err?.message || "Query failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question over uploaded sources" />
      <Button type="primary" onClick={run} loading={loading}>Ask</Button>
    </div>
  );
}
