// Single source of truth for upload limits. The backend enforces the same two
// values (CONTRACT_MAX_BYTES / CONTRACT_ALLOWED_EXTS in main.py); keeping the
// client copy in one module stops the chat paperclip and the landing hero from
// drifting apart and promising a size the server will reject.
export const ACCEPTED_EXTS = ['.docx', '.doc', '.pdf', '.txt']
export const MAX_FILE_BYTES = 10 * 1024 * 1024

export type UploadRejection = 'ext' | 'size'

export function validateUpload(file: File): UploadRejection | null {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!ACCEPTED_EXTS.includes(ext)) return 'ext'
  if (file.size > MAX_FILE_BYTES) return 'size'
  return null
}
