import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { FilesTab } from './tabs/FilesTab';

const root = document.getElementById('root');
if (!root) throw new Error('No #root element found');

createRoot(root).render(
  <StrictMode>
    <div className="container portal-container" data-theme="dark">
      <FilesTab />
    </div>
  </StrictMode>,
);
