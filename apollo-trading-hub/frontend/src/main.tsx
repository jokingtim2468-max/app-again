import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';

if (import.meta.env.VITE_DEMO === '1') {
  const { installDemo } = await import('./demo/demo');
  installDemo();
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
