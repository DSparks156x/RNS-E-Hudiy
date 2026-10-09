export interface PortalFile { name: string; path: string; size: number; modified: number; download_url: string; date?: string | null; sequence?: number | null; }
export interface PortalFolder { path: string; count: number; total_size: number; modified: number; date?: string | null; archive_url: string | null; }
export interface PortalCollection {
  id: string; label: string; description: string; kind: 'firmware' | 'logs' | 'readouts';
  upload: boolean; extensions: string[]; max_size: number; count: number; total_size: number;
  archive_url: string | null; files: PortalFile[]; groups?: PortalFolder[];
}
export interface PortalCatalog { pin_required: boolean; all_logs_archive_url: string | null; collections: PortalCollection[]; }
export type FileGroup = 'recordings' | 'debug' | 'controllers';
export const collectionGroup = (collection: PortalCollection): FileGroup =>
  collection.id === 'drive_logs' ? 'recordings' : collection.kind === 'logs' ? 'debug' : 'controllers';
const naturalCompare = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });
function fileDate(file: PortalFile) {
  if (file.date) return file.date;
  const match = file.path.match(/(?:^|[/_])(\d{4})-?(\d{2})-?(\d{2})(?=[_/. -]|$)/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : new Date(file.modified * 1000).toLocaleDateString('sv-SE');
}
export function visibleFiles(files: PortalFile[], search: string, sort: string) {
  const query = search.trim().toLocaleLowerCase();
  return files.filter(file => !query || `${file.name} ${file.path}`.toLocaleLowerCase().includes(query))
    .sort((a, b) => sort === 'name' ? naturalCompare(a.name, b.name) : sort === 'size' ? b.size - a.size
      : fileDate(b).localeCompare(fileDate(a)) || ((b.sequence || 0) - (a.sequence || 0)) || b.modified - a.modified || naturalCompare(b.path, a.path));
}
export function folderFiles(files: PortalFile[], groups: PortalFolder[] = [], sort = 'date', groupDates = false) {
  const folders = new Map<string, { path: string; label: string; key: string; files: PortalFile[]; archive_url: string | null }>();
  for (const file of files) {
    const path = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : '';
    const key = path || (groupDates ? `date:${fileDate(file)}` : '');
    if (!folders.has(key)) folders.set(key, { path, key, label: path || (groupDates ? fileDate(file) : ''), files: [], archive_url: groups.find(group => group.path === path)?.archive_url || null });
    folders.get(key)!.files.push(file);
  }
  return [...folders.values()].sort((a, b) => {
    if (!a.label || !b.label) return a.label ? -1 : b.label ? 1 : 0;
    if (sort === 'name') return naturalCompare(a.label, b.label);
    if (sort === 'size') return b.files.reduce((size, file) => size + file.size, 0) - a.files.reduce((size, file) => size + file.size, 0);
    return fileDate(b.files[0]).localeCompare(fileDate(a.files[0])) || naturalCompare(b.path, a.path);
  });
}
export function validateFile(file: Pick<File, 'name' | 'size'>, target: PortalCollection): string | null {
  const extension = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : '';
  if (target.extensions.length && !target.extensions.some(item => item.toLowerCase() === extension)) return `Choose a ${target.extensions.join(' or ')} file for ${target.label}.`;
  if (file.size > target.max_size) return `This file exceeds the ${target.max_size / 1024 / 1024} MB limit.`;
  if (!file.size) return 'The selected file is empty.';
  return null;
}
