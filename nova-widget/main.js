/**
 * NOVA Widget — Electron main process
 */

const path = require('path');
const fs   = require('fs');

// En Electron 33+, las APIs se inyectan en el event loop DESPUÉS de cargar el módulo.
// Usamos setImmediate para esperar a que el proceso Electron esté listo.
setImmediate(main);

function main() {
  const {
    app, BrowserWindow, Tray, Menu, ipcMain,
    globalShortcut, screen, nativeImage, shell
  } = require('electron');

  // ── Constantes ───────────────────────────────────────
  const SIZES = {
    small:  { w: 240, h: 240 },
    medium: { w: 440, h: 440 },
    large:  { w: 640, h: 640 },
  };
  let currentSize = 'small';
  let isHidden    = false;
  let gamingMode  = false;
  let cpuHigh     = 0;
  let win, tray;

  // ── Config persistente ────────────────────────────────
  function configPath() { return path.join(app.getPath('userData'), 'nova-config.json'); }
  function loadConfig() {
    try { return JSON.parse(fs.readFileSync(configPath(), 'utf8')); }
    catch { return {}; }
  }
  function saveConfig(data) {
    const current = loadConfig();
    fs.writeFileSync(configPath(), JSON.stringify({ ...current, ...data }, null, 2));
  }

  // ── Tray icon ─────────────────────────────────────────
  function buildTrayIcon() {
    const icoPath = path.join(__dirname, 'icon.ico');
    if (fs.existsSync(icoPath)) return nativeImage.createFromPath(icoPath);
    const b64 = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAwElEQVR4Ae3WMQqDQBCF4Xd3J' +
                'eBVPIAnsBcQPIUnsBdQPIUnsBfwCF7AK3gFr+AV3MCF/Q8WJIGwIZn3YGBgePDNMDNhxhhCCC' +
                'GEEEIIIYQQQgghhBBCCCGEEEIIIYQQQgghhBBCCCGEEEIIIYQQQgghhBBCCCGEEEIIIYQQQggh' +
                'hBBCCCGEEEIIIYQQQgghhBBCCCGEEEIIIYQQQgghhBBCCCGEEEIIIYQQQgghhBBCCCGEEEIIIY' +
                'QQQgghhBBCCCH+1Rc3kAjQWAAAAABJRU5ErkJggg==';
    return nativeImage.createFromDataURL(`data:image/png;base64,${b64}`);
  }

  // ── Crear ventana ─────────────────────────────────────
  function createWindow() {
    const cfg     = loadConfig();
    const display = screen.getPrimaryDisplay();
    const { width: sw, height: sh } = display.workAreaSize;
    const sz = SIZES[cfg.size || 'small'];
    const defaultX = sw - sz.w - 20;
    const defaultY = sh - sz.h - 20;

    win = new BrowserWindow({
      width:  sz.w,
      height: sz.h,
      x: cfg.x ?? defaultX,
      y: cfg.y ?? defaultY,
      transparent:     true,
      backgroundColor: '#00000000',
      frame:           false,
      alwaysOnTop:     true,
      skipTaskbar:     true,
      resizable:       false,
      hasShadow:       false,
      type: process.platform === 'linux' ? 'desktop' : undefined,
      webPreferences: {
        preload:          path.join(__dirname, 'preload.js'),
        nodeIntegration:  false,
        contextIsolation: true,
      }
    });

    win.setAlwaysOnTop(true, 'screen-saver');
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.loadFile(path.join(__dirname, '..', 'nova-orb-3d.html'));

    win.webContents.session.setPermissionRequestHandler((wc, perm, cb) => {
      cb(['media', 'microphone', 'audioCapture'].includes(perm));
    });

    let hoverInterval = setInterval(() => {
      if (!win || win.isDestroyed()) return;
      const cursor = screen.getCursorScreenPoint();
      const bounds = win.getBounds();
      const cx = bounds.x + bounds.width  / 2;
      const cy = bounds.y + bounds.height / 2;
      const dist = Math.hypot(cursor.x - cx, cursor.y - cy);
      const radius = Math.min(bounds.width, bounds.height) * 0.43;
      win.setIgnoreMouseEvents(dist >= radius, { forward: true });
    }, 50);

    win.on('closed', () => { clearInterval(hoverInterval); win = null; });
  }

  // ── Gaming mode ───────────────────────────────────────
  function checkGamingMode() {
    fetch('http://localhost:5000/status', { signal: AbortSignal.timeout(600) })
      .then(r => r.json())
      .then(d => {
        if (!d.cpu) return;
        if (d.cpu > 72) {
          cpuHigh++;
          if (cpuHigh >= 8 && !gamingMode) activateGamingMode();
        } else {
          if (cpuHigh > 0) cpuHigh--;
          if (cpuHigh === 0 && gamingMode) deactivateGamingMode();
        }
      })
      .catch(() => {});
  }

  function activateGamingMode() {
    if (!win || gamingMode) return;
    gamingMode = true;
    currentSize = 'small';
    const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize;
    const sz = SIZES.small;
    win.setSize(sz.w, sz.h);
    win.setPosition(sw - sz.w - 10, sh - sz.h - 10);
    win.webContents.executeJavaScript(`window.setMode('concentration', null)`);
    updateTrayMenu();
  }

  function deactivateGamingMode() {
    if (!win || !gamingMode) return;
    gamingMode  = false;
    cpuHigh     = 0;
    currentSize = loadConfig().size || 'small';
    const sz = SIZES[currentSize];
    win.setSize(sz.w, sz.h);
    win.webContents.executeJavaScript(`window.setMode('idle', null)`);
    updateTrayMenu();
  }

  // ── Resize ────────────────────────────────────────────
  function resizeTo(key) {
    if (!win) return;
    currentSize = key;
    const sz = SIZES[key];
    const [cx, cy] = win.getPosition();
    const [cw, ch] = win.getSize();
    win.setSize(sz.w, sz.h);
    win.setPosition(cx + Math.round((cw - sz.w) / 2), cy + Math.round((ch - sz.h) / 2));
    saveConfig({ size: key });
    updateTrayMenu();
  }

  // ── Tray menu ─────────────────────────────────────────
  function buildTrayMenu() {
    return Menu.buildFromTemplate([
      { label: 'N.O.V.A Widget v2.1', enabled: false },
      { type: 'separator' },
      {
        label: isHidden ? 'Mostrar NOVA' : 'Ocultar NOVA',
        click: () => {
          isHidden ? (win.show(), isHidden = false) : (win.hide(), isHidden = true);
          updateTrayMenu();
        }
      },
      { type: 'separator' },
      {
        label: 'Modo',
        submenu: [
          { label: 'Idle',          click: () => win.webContents.executeJavaScript(`window.setMode('idle',null)`) },
          { label: 'Escuchar',      click: () => win.webContents.executeJavaScript(`window.setMode('listening',null)`) },
          { label: 'Procesar',      click: () => win.webContents.executeJavaScript(`window.setMode('thinking',null)`) },
          { label: 'Hablar',        click: () => win.webContents.executeJavaScript(`window.setMode('talking',null)`) },
          { label: 'Concentración', click: () => win.webContents.executeJavaScript(`window.setMode('concentration',null)`) },
          { label: 'Creativo',      click: () => win.webContents.executeJavaScript(`window.setMode('creative',null)`) },
          { label: 'Alerta Oracle', click: () => win.webContents.executeJavaScript(`window.setMode('alert',null)`) },
        ]
      },
      {
        label: 'Tamaño',
        submenu: [
          { label: `Pequeño  (240px)${currentSize==='small'  ? ' ✓':''}`, click: () => resizeTo('small')  },
          { label: `Mediano  (440px)${currentSize==='medium' ? ' ✓':''}`, click: () => resizeTo('medium') },
          { label: `Grande   (640px)${currentSize==='large'  ? ' ✓':''}`, click: () => resizeTo('large')  },
        ]
      },
      { type: 'separator' },
      { label: gamingMode ? 'Gaming Mode: ON (auto)' : 'Gaming Mode: OFF', enabled: false },
      { type: 'separator' },
      {
        label: 'Arrancar con Windows',
        type: 'checkbox',
        checked: app.getLoginItemSettings().openAtLogin,
        click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked })
      },
      { type: 'separator' },
      { label: 'Apagar NOVA', click: () => { if(win) win.webContents.executeJavaScript('window.triggerShutdown()'); setTimeout(()=>app.quit(),3000); } },
      { label: 'Salir', click: () => app.quit() },
    ]);
  }

  function updateTrayMenu() {
    if (tray) tray.setContextMenu(buildTrayMenu());
  }

  // ── App ready ─────────────────────────────────────────
  app.whenReady().then(() => {
    createWindow();

    ipcMain.on('drag-start', (_, { x, y }) => {
      win._dragStart = { x, y };
      win._dragPos   = win.getPosition();
    });
    ipcMain.on('drag-move', (_, { x, y }) => {
      if (!win._dragStart || !win) return;
      win.setPosition(
        win._dragPos[0] + (x - win._dragStart.x),
        win._dragPos[1] + (y - win._dragStart.y)
      );
    });
    ipcMain.on('drag-end', () => {
      win._dragStart = null;
      if (win) { const [wx, wy] = win.getPosition(); saveConfig({ x: wx, y: wy }); }
    });
    ipcMain.handle('set-mode-from-tray', (_, mode) => {
      if (win) win.webContents.executeJavaScript(`window.setMode('${mode}', null)`);
    });

    setInterval(checkGamingMode, 5000);

    const icon = buildTrayIcon();
    tray = new Tray(icon);
    tray.setToolTip('N.O.V.A — Neural Operative Virtual Assistant');
    tray.setContextMenu(buildTrayMenu());
    tray.on('double-click', () => {
      if (!win) return;
      isHidden ? (win.show(), isHidden = false) : (win.hide(), isHidden = true);
      updateTrayMenu();
    });

    globalShortcut.register('Super+N', () => {
      if (!win) return;
      if (isHidden) { win.show(); win.focus(); isHidden = false; }
      else          { win.hide(); isHidden = true; }
      updateTrayMenu();
    });

    const modeOrder = ['idle','listening','thinking','talking','concentration','creative'];
    let modeIndex = 0;
    globalShortcut.register('Super+Shift+N', () => {
      modeIndex = (modeIndex + 1) % modeOrder.length;
      if (win) win.webContents.executeJavaScript(`window.setMode('${modeOrder[modeIndex]}',null)`);
    });
  });

  app.on('will-quit', () => globalShortcut.unregisterAll());
  app.on('window-all-closed', (e) => e.preventDefault());
}
