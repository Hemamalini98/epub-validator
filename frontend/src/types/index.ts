// ─── Stored book (persisted to localStorage after upload) ────────────────────
export interface Book {
  folder_name: string;
  epub_path: string;
  uploaded_at: string;   // ISO date string YYYY-MM-DD
  total_files: number;
}

// ─── GET /files/{folderName} ──────────────────────────────────────────────────
export interface XHTMLFile {
  file_name: string;
  path?: string;          // actual backend field
  relative_path?: string; // fallback alias
}

export interface FilesResponse {
  status: boolean;
  folder?: string;
  total_files?: number;
  files?: XHTMLFile[];
  message?: string;
}

// ─── POST /upload ─────────────────────────────────────────────────────────────
export interface UploadSuccessResponse {
  status: true;
  message?: string;
  folder_name?: string;       // may be added by backend
  extract_folder?: string;    // actual backend field: "uploads/{name}/extract"
  epub_extract_path?: string;
  epub_path?: string;
  epub_file?: string;
  pdf_file?: string;
  files?: string[];
}

export interface UploadErrorResponse {
  status: false;
  message: string;
}

export type UploadResponse = UploadSuccessResponse | UploadErrorResponse;

// ─── Upload flow stages ───────────────────────────────────────────────────────
export type UploadStage =
  | 'idle'
  | 'dragging'
  | 'uploading'
  | 'extracting'
  | 'completed'
  | 'failed';

// ─── GET /validate/{folderName} ───────────────────────────────────────────────
export interface ValidationIssue {
  type: string;
  category?: 'Error' | 'Warning';
  message?: string;
  href?: string;
  id?: string;
  expected_text?: string;
  actual_text?: string;
  status_code?: number;
  [key: string]: unknown;
}

export interface ValidationFileEntry {
  rule_id: string;
  rule_name: string;
  function: string;
  target_path: string;
  file_pattern: string;
  file_details: {
    file_name: string;
    full_path: string;
    relative_path: string;
    folder_name: string;
  };
  result: {
    issues_count: number;
    issues: ValidationIssue[];
  };
}

export interface ValidationApiResponse {
  folder: string;
  epub_path: string;
  files: ValidationFileEntry[];
}

// ─── Per-file aggregated result (computed on frontend) ────────────────────────
export type XHTMLFileStatus = 'pending' | 'passed' | 'warning' | 'failed';

export interface FileIssueCount {
  errors: number;
  warnings: number;
}
