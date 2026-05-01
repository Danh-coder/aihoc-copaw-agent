import { useState, useEffect } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Button, Upload, Table, Tag, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { sourcesApi } from "@/api/modules/sources";
import QueryBox from "./QueryBox";
import styles from "./index.module.less";

export default function RagSourcesPage() {
  const [sources, setSources] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchList = async () => {
    setLoading(true);
    try {
      const res = await sourcesApi.list();
      setSources(res as any[]);
    } catch (err: any) {
      message.error(err?.message || "Failed to load sources");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchList();
  }, []);

  const props = {
    beforeUpload: async (file: File) => {
      try {
        await sourcesApi.upload(file);
        message.success(`Uploaded: ${file.name}`);
        fetchList();
      } catch (err: any) {
        message.error(err?.message || "Upload failed");
      }
      return false; // prevent auto upload by antd
    },
    showUploadList: false,
  };

  const handleAnswer = (a: any) => {
    if (a?.answer) {
      message.info(a.answer, 10);
    }
  };

  return (
    <div className={styles.container}>
      <PageHeader items={[{ title: "Settings" }, { title: "RAG Sources" }]} />
      <div style={{ marginTop: 12, marginBottom: 12 }}>
        <QueryBox onAnswer={handleAnswer} />
      </div>

      <div style={{ marginBottom: 16 }}>
        <Upload {...props}>
          <Button icon={<UploadOutlined />}>Upload PDF</Button>
        </Upload>
      </div>

      <Table
        dataSource={sources}
        loading={loading}
        rowKey={(r) => r.id}
        columns={[
          { title: "ID", dataIndex: "id", key: "id" },
          { title: "Name", dataIndex: "name", key: "name" },
          { title: "Status", dataIndex: "status", key: "status", render: (s: string) => <Tag>{s}</Tag> },
          { title: "Filename", dataIndex: "filename", key: "filename" },
        ]}
      />
    </div>
  );
}
