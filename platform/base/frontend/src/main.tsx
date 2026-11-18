import { createRoot } from 'react-dom/client';
import App from './App';
import { AppTheme } from './framework';

const root = createRoot(document.getElementById('root')!);
root.render(
  <AppTheme>
    <App />
  </AppTheme>
);
