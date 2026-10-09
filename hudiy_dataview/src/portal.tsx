import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { FilePortal } from './FilePortal';

const root = document.getElementById('root');
if (!root) throw new Error('No #root element found');

createRoot(root).render(
  <StrictMode>
    <FilePortal />
  </StrictMode>,
);
