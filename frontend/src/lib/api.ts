import axios from 'axios';
import type { Book, FilesResponse, UploadResponse, ValidationApiResponse } from '@/types';

const client = axios.create({ timeout: 60_000 });

function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data;
    if (data?.message) return String(data.message);
    if (data?.detail)  return String(data.detail);
  }
  if (err instanceof Error) return err.message;
  return 'An unexpected error occurred';
}

export async function uploadFile(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);

  try {
    const { data } = await client.post<UploadResponse>('/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      },
    });
    return data;
  } catch (err) {
    throw new Error(extractErrorMessage(err));
  }
}

export async function getFiles(folderName: string): Promise<FilesResponse> {
  const { data } = await client.get<FilesResponse>(`/file-data/${folderName}`);
  return data;
}

export async function validateFolder(folderName: string): Promise<ValidationApiResponse> {
  const { data } = await client.get<ValidationApiResponse>(`/validate/${folderName}`, {
    timeout: 10 * 60 * 1000,
  });
  return data;
}

export async function getFileContent(folderName: string, filePath: string): Promise<string> {
  const encoded = filePath.replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/');
  const { data } = await client.get<string>(`/file-data/${folderName}/${encoded}`, {
    responseType: 'text',
  });
  return data;
}

export async function saveFileContent(
  folderName: string,
  filePath: string,
  content: string,
): Promise<void> {
  const encoded = filePath.replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/');
  try {
    await client.put(`/file-data/${folderName}/${encoded}`, { content });
  } catch (err) {
    throw new Error(extractErrorMessage(err));
  }
}

export async function validateFile(
  folderName: string,
  fileName: string,
): Promise<ValidationApiResponse> {
  const { data } = await client.get<ValidationApiResponse>(`/validate/${folderName}`, {
    params: { file: fileName },
    timeout: 10 * 60 * 1000,
  });
  return data;
}

export async function getPdfPage(
  folderName: string,
  fileName: string,
): Promise<{ page: number; total_pages: number }> {
  const { data } = await client.get<{ page: number; total_pages: number }>(
    `/pdf/${folderName}/page`,
    { params: { file: fileName } },
  );
  return data;
}

export async function getBooks(): Promise<Book[]> {
  const { data } = await client.get<Book[]>('/books');
  return data;
}

export async function deleteBook(folderName: string): Promise<void> {
  try {
    await client.delete(`/books/${folderName}`);
  } catch (err) {
    throw new Error(extractErrorMessage(err));
  }
}

export interface ExportConfirmResponse {
  status: 'confirm';
  message: string;
}

export async function exportEpub(
  folderName: string,
  stats: { failed: number; warnings: number; pending: number },
  force = false,
): Promise<ExportConfirmResponse | Blob> {
  try {
    const response = await client.post(
      `/export/${folderName}`,
      { ...stats, force },
      { responseType: 'blob', timeout: 60_000 },
    );
    const contentType = (response.headers['content-type'] as string) ?? '';
    if (contentType.includes('application/json')) {
      const text = await (response.data as Blob).text();
      return JSON.parse(text) as ExportConfirmResponse;
    }
    return response.data as Blob;
  } catch (err) {
    // When responseType is 'blob', axios wraps the error body as a Blob too
    if (axios.isAxiosError(err) && err.response?.data instanceof Blob) {
      let parsed: { detail?: string; message?: string } | null = null;
      try {
        const text = await err.response.data.text();
        parsed = JSON.parse(text);
      } catch { /* not JSON */ }
      if (parsed) throw new Error(parsed.detail ?? parsed.message ?? 'Export failed');
    }
    throw new Error(extractErrorMessage(err));
  }
}

/** Derive folder_name from the upload response, falling back to the filename. */
export function resolveFolderName(response: UploadResponse, file: File): string {
  if (!response.status) return file.name.replace(/\.[^.]+$/, '');
  if (response.folder_name) return response.folder_name;
  if (response.extract_folder) {
    // "uploads/{folder_name}/extract" → folder_name
    const parts = response.extract_folder.replace(/\\/g, '/').split('/');
    if (parts.length >= 2 && parts[1]) return parts[1];
  }
  return file.name.replace(/\.[^.]+$/, '');
}
