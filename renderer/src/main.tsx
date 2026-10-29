import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { MusicPlayerProvider } from './MusicPlayer';
import './styles.css';
import './taste.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><MusicPlayerProvider><App /></MusicPlayerProvider></React.StrictMode>);
