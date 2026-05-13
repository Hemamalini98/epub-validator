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
  const { data } = await client.get<FilesResponse>(`/files/${folderName}`);
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
  const { data } = await client.get<string>(`/files/${folderName}/${encoded}`, {
    responseType: 'text',
  });
  return data;
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
