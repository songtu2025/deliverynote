export interface InputVersion {
  id: number;
  kind: string;
  name: string;
  original_name: string;
  active: boolean;
  created_by: number;
  created_at: string;
}

export interface PositionIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  row_numbers: number[];
  before?: number;
  after?: number;
}

interface InputVersionSummary {
  kind: string;
  row_count: number;
  columns: string[];
  metrics: Record<string, number>;
  issues: PositionIssue[];
}

export type InputVersionPreviewValue = string | number | boolean | null;

interface InputVersionPreview {
  kind: string;
  columns: string[];
  rows: Record<string, InputVersionPreviewValue>[];
  total: number;
  offset: number;
  limit: number;
}

export interface InputVersionInspection {
  summary: InputVersionSummary;
  preview: InputVersionPreview;
}
