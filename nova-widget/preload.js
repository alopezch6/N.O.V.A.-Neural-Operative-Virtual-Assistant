/**
 * NOVA Widget — Preload script (bridge renderer ↔ main)
 *
 * - Expone window.electronAPI para drag y comunicación
 * - Inyecta CSS para ocultar controles en modo widget
 * - Añade handle de arrastre en la esquina superior izquierda
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  dragStart: (x, y)    => ipcRenderer.send('drag-start', { x, y }),
  dragMove:  (x, y)    => ipcRenderer.send('drag-move',  { x, y }),
  dragEnd:   ()        => ipcRenderer.send('drag-end'),
  onSetMode: (cb)      => ipcRenderer.on('set-mode', (_, m) => cb(m)),
  onGamingMode: (cb)   => ipcRenderer.on('gaming-mode', (_, a) => cb(a)),
});

// Cuando el DOM esté listo, inyecta ajustes visuales para modo widget
window.addEventListener('DOMContentLoaded', () => {

  // ── Ocultar botones de control (se usan desde el tray) ──
  const style = document.createElement('style');
  style.textContent = `
    html, body       { background: transparent !important; }
    #bg-light        { display: none !important; }
    body::before     { display: none !important; }
    .scan            { display: none !important; }
    .mode-controls   { display: none !important; }
    .drag-hint       { display: none !important; }
    .info-left, .info-right { display: none !important; }
    .nova-title      { display: none !important; }
    .nova-sub        { display: none !important; }
    .mode-badge      { display: none !important; }
    .status-wrap     { display: none !important; }
    .alert-bar, .alert-text { display: none !important; }
    .corner          { width: 14px; height: 14px; }
    .corner-tl       { top: 4px;  left: 4px; }
    .corner-tr       { top: 4px;  right: 4px; }
    .corner-bl       { bottom: 4px; left: 4px; }
    .corner-br       { bottom: 4px; right: 4px; }
    #c {
      filter:
        drop-shadow(0 0 6px rgba(168,85,247,0.9))
        drop-shadow(0 0 18px rgba(168,85,247,0.5))
        drop-shadow(0 0 40px rgba(34,211,238,0.25));
    }
  `;
  document.head.appendChild(style);

  // ── Handle de arrastre — zona superior con icono ⠿ ──
  const handle = document.createElement('div');
  handle.id = 'drag-handle';
  handle.textContent = '⠿';
  handle.style.cssText = `
    position: fixed; top: 5px; left: 50%; transform: translateX(-50%);
    width: 28px; height: 14px; line-height: 14px; text-align: center;
    font-size: 10px; color: rgba(168,85,247,0.35);
    cursor: grab; z-index: 9999; user-select: none;
    transition: color 0.2s;
  `;
  handle.addEventListener('mouseenter', () => { handle.style.color = 'rgba(168,85,247,0.85)'; });
  handle.addEventListener('mouseleave', () => { handle.style.color = 'rgba(168,85,247,0.35)'; });

  // Drag logic
  handle.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.style.cursor = 'grabbing';
    window.electronAPI.dragStart(e.screenX, e.screenY);

    const onMove = (ev) => window.electronAPI.dragMove(ev.screenX, ev.screenY);
    const onUp   = ()   => {
      window.electronAPI.dragEnd();
      handle.style.cursor = 'grab';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup',   onUp);
  });

  document.body.appendChild(handle);

  // ── Recibe comandos de modo desde main ──
  window.electronAPI.onSetMode((mode) => {
    if (window.setMode) window.setMode(mode, null);
  });

  // ── Gaming mode: ocultar HUD panels completamente ──
  window.electronAPI.onGamingMode((active) => {
    const panels = document.querySelectorAll('.info-left,.info-right,.nova-title,.mode-badge,.status-wrap');
    panels.forEach(p => { p.style.opacity = active ? '0' : ''; });
  });
});
