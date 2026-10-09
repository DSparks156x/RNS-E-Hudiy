export interface PortalFile { name: string; path: string; size: number; modified: number; download_url: string; }
export interface PortalCollection {
  id: string; label: string; description: string; kind: 'firmware' | 'logs' | 'readouts';
  upload: boolean; extensions: string[]; max_size: number; count: number; total_size: number;
  archive_url: string | null; files: PortalFile[];
}
export interface PortalCatalog { pin_required: boolean; all_logs_archive_url: string | null; collections: PortalCollection[]; }
export type FileGroup = 'recordings' | 'debug' | 'controllers';
export const collectionGroup = (collection: PortalCollection): FileGroup =>
  collection.id === 'drive_logs' ? 'recordings' : collection.kind === 'logs' ? 'debug' : 'controllers';
export function visibleFiles(files: PortalFile[], search: string, sort: string) {
  const query = search.trim().toLocaleLowerCase();
  return files.filter(file => !query || `${file.name} ${file.path}`.toLocaleLowerCase().includes(query))
    .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'size' ? b.size - a.size : b.modified - a.modified);
}
export function validateFile(file: Pick<File, 'name' | 'size'>, target: PortalCollection): string | null {
  const extension = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : '';
  if (target.extensions.length && !target.extensions.some(item => item.toLowerCase() === extension)) return `Choose a ${target.extensions.join(' or ')} file for ${target.label}.`;
  if (file.size > target.max_size) return `This file exceeds the ${target.max_size / 1024 / 1024} MB limit.`;
  if (!file.size) return 'The selected file is empty.';
  return null;
}
