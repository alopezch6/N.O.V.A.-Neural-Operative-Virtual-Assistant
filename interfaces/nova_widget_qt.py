"""
NOVA Widget — PySide6 + QWebEngineView
Ventana sin marco, siempre encima, transparencia via color key (negro = transparente).
"""

import sys
import os
import ctypes
import math
from pathlib import Path

import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    _nvml_ok = True
except Exception:
    _nvml_ok = False

try:
    import pyaudio as _pa
    import numpy as _np
    import threading as _thr

    _AUDIO_SR   = 44100
    _AUDIO_BS   = 2048
    _N_BANDS    = 64
    _FREQ_EDGES = _np.logspace(_np.log10(60), _np.log10(16000), _N_BANDS + 1)
    _FREQS      = _np.fft.rfftfreq(_AUDIO_BS, 1.0 / _AUDIO_SR)
    _BAND_IDX   = [
        _np.where((_FREQS >= _FREQ_EDGES[i]) & (_FREQS < _FREQ_EDGES[i + 1]))[0]
        for i in range(_N_BANDS)
    ]
    _aud_bands  = _np.zeros(_N_BANDS)
    _aud_energy = 0.0
    _aud_peak   = _np.ones(_N_BANDS) * 1e-6
    _aud_lock   = _thr.Lock()
    _audio_ok   = True

    def _audio_cb(in_data, frame_count, time_info, status):
        global _aud_energy
        raw  = _np.frombuffer(in_data, dtype=_np.float32)
        mono = raw.reshape(-1, 2).mean(axis=1) if raw.size == frame_count * 2 else raw[:frame_count]
        if len(mono) < _AUDIO_BS:
            return (None, _pa.paContinue)
        mono  = mono[:_AUDIO_BS]
        fft   = _np.abs(_np.fft.rfft(mono * _np.hanning(_AUDIO_BS)))
        bands = _np.array([
            _np.sqrt(_np.mean(fft[idx] ** 2)) if len(idx) else 0.0
            for idx in _BAND_IDX
        ])
        _aud_peak[:] = _np.maximum(_aud_peak * 0.995, bands)
        _aud_peak[:] = _np.maximum(_aud_peak, 1e-6)
        with _aud_lock:
            _aud_bands[:] = _np.clip(_np.sqrt(bands / _aud_peak), 0, 1)
            _aud_energy   = float(min(1.0, _np.sqrt(_np.mean(mono ** 2)) * 40))
        return (None, _pa.paContinue)

except Exception:
    _audio_ok = False


def _find_loopback_device(pa_inst):
    """Busca Mezcla estéreo / Stereo Mix u otro input de loopback del sistema."""
    keywords = ['stereo mix', 'mezcla est', 'what u hear', 'wave out mix',
                'sonar - stream', 'sonar - gaming']
    for i in range(pa_inst.get_device_count()):
        d = pa_inst.get_device_info_by_index(i)
        if d['maxInputChannels'] > 0:
            name = d['name'].lower()
            if any(k in name for k in keywords):
                return i, min(2, int(d['maxInputChannels']))
    return None, None


def _start_audio_stream():
    if not _audio_ok:
        return None
    try:
        pa      = _pa.PyAudio()
        dev, ch = _find_loopback_device(pa)
        if dev is None:
            pa.terminate()
            return None
        stream = pa.open(
            format=_pa.paFloat32, channels=ch, rate=_AUDIO_SR,
            input=True, input_device_index=dev,
            frames_per_buffer=_AUDIO_BS, stream_callback=_audio_cb,
        )
        stream.start_stream()
        return (pa, stream)
    except Exception:
        return None

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--enable-transparent-visuals --disable-features=WebRtcHideLocalIpsWithMdns"

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineScript
from PySide6.QtCore import Qt, QUrl, QTimer, QPoint, QObject, QEvent
from PySide6.QtGui import QColor, QCursor, QRegion

user32            = ctypes.windll.user32
dwmapi            = ctypes.windll.dwmapi
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
LWA_COLORKEY      = 0x00000001
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR             = 34
DWMWCP_DONOTROUND              = 1
DWMWA_COLOR_NONE               = 0xFFFFFFFE


class WebviewDragFilter(QObject):
    """Intercepta clicks izquierdos del webview para arrastrar la ventana."""
    def __init__(self, window):
        super().__init__(window)
        self._win = window

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            self._win._dragging = True
            self._win._drag_offset = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            if self._win._hwnd:
                _set_click_through(self._win._hwnd, False)
            return True
        if t == QEvent.Type.MouseMove and self._win._dragging and (event.buttons() & Qt.LeftButton):
            self._win.move(event.globalPosition().toPoint() - self._win._drag_offset)
            return True
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._win._dragging = False
            self._win._wander_home = self._win.frameGeometry().topLeft()
            return True
        return False


def _set_click_through(hwnd: int, enable: bool):
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enable:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED)


class NovaWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        pass


class NovaWidget(QMainWindow):
    SIZE_DEFAULT     = 440
    ORB_RADIUS_RATIO = 0.43

    def __init__(self, size: int = SIZE_DEFAULT):
        super().__init__()
        self._size     = size
        self._dragging = False
        self._drag_offset = QPoint()
        self._click_through_active = False
        self._hwnd     = None  # cached on first show

        self._wander_time = 0.0
        self._wander_home = QPoint()

        self._setup_window()
        self._setup_webview()
        self._position_on_screen()
        self._start_click_through_timer()
        self._start_wander_timer()
        self._start_system_monitor()
        self._audio_stream = _start_audio_stream()
        self._start_audio_monitor()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFixedSize(self._size, self._size)

    def _setup_webview(self):
        page = NovaWebPage(self)
        page.setBackgroundColor(QColor(0, 0, 0, 0))

        self._webview = QWebEngineView(self)
        self._webview.setPage(page)
        self._webview.setGeometry(0, 0, self._size, self._size)

        s = self._webview.settings()
        s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)

        self._inject_electron_api()
        self._webview.installEventFilter(WebviewDragFilter(self))

        html_path = Path(__file__).resolve().parents[1] / "nova-orb-float.html"
        self._webview.load(QUrl.fromLocalFile(str(html_path)))

    def _inject_electron_api(self):
        script = QWebEngineScript()
        script.setName("nova-electron-api")
        script.setSourceCode(
            "window.electronAPI = { widget:'pyside6', onModeChange:function(cb){}, onResize:function(cb){} };"
        )
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        self._webview.page().scripts().insert(script)

    def _position_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        home = QPoint(screen.right() - self._size - 20, screen.bottom() - self._size - 20)
        self.move(home)
        self._wander_home = home

    def show(self):
        super().show()
        self._hwnd = int(self.winId())
        mask = QRegion(0, 0, self._size, self._size, QRegion.RegionType.Ellipse)
        self.setMask(mask)
        self._webview.setMask(mask)
        self._remove_dwm_border()

    def _remove_dwm_border(self):
        val = ctypes.c_uint(DWMWCP_DONOTROUND)
        dwmapi.DwmSetWindowAttribute(self._hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(val), ctypes.sizeof(val))
        val = ctypes.c_uint(DWMWA_COLOR_NONE)
        dwmapi.DwmSetWindowAttribute(self._hwnd, DWMWA_BORDER_COLOR, ctypes.byref(val), ctypes.sizeof(val))

    def _start_audio_monitor(self):
        if not _audio_ok:
            return
        self._aud_timer = QTimer(self)
        self._aud_timer.timeout.connect(self._push_audio)
        self._aud_timer.start(50)

    def _push_audio(self):
        if not self._hwnd:
            return
        with _aud_lock:
            bands  = _aud_bands.tolist()
            energy = float(_aud_energy)
        bstr = '[' + ','.join(f'{v:.3f}' for v in bands) + ']'
        js   = f'window.updateAudioData&&window.updateAudioData({{b:{bstr},e:{energy:.3f}}});'
        self._webview.page().runJavaScript(js)

    def _start_system_monitor(self):
        psutil.cpu_percent(interval=None)  # primera llamada siempre devuelve 0 — descartarla
        self._sys_timer = QTimer(self)
        self._sys_timer.timeout.connect(self._update_system_load)
        self._sys_timer.start(2000)

    def _update_system_load(self):
        if not self._hwnd:
            return
        cpu = psutil.cpu_percent(interval=None)
        gpu = 0
        if _nvml_ok:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
                gpu = util.gpu
            except Exception:
                pass
        js = f"window.updateSystemLoad&&window.updateSystemLoad({{cpu:{cpu:.1f},gpu:{gpu:.1f}}});"
        self._webview.page().runJavaScript(js)

    def _start_wander_timer(self):
        self._wander_timer = QTimer(self)
        self._wander_timer.timeout.connect(self._update_wander)
        self._wander_timer.start(50)

    def _update_wander(self):
        if self._dragging:
            return
        self._wander_time += 0.05
        t = self._wander_time
        dx = int(math.sin(t * 0.19) * 32 + math.sin(t * 0.07) * 16)
        dy = int(math.sin(t * 0.25) * 26 + math.cos(t * 0.11) * 14)
        screen = QApplication.primaryScreen().availableGeometry()
        new_x  = max(screen.left(), min(screen.right()  - self._size, self._wander_home.x() + dx))
        new_y  = max(screen.top(),  min(screen.bottom() - self._size, self._wander_home.y() + dy))
        self.move(new_x, new_y)

    def _start_click_through_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_click_through)
        self._timer.start(40)

    def _update_click_through(self):
        if self._dragging or self._hwnd is None:
            return
        cursor_local = self.mapFromGlobal(QCursor.pos())
        dist    = math.hypot(cursor_local.x() - self._size / 2, cursor_local.y() - self._size / 2)
        outside = dist > self._size * self.ORB_RADIUS_RATIO
        if outside != self._click_through_active:
            self._click_through_active = outside
            _set_click_through(self._hwnd, outside)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging    = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if self._hwnd:
                _set_click_through(self._hwnd, False)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._wander_home = self.frameGeometry().topLeft()

    def mouseDoubleClickEvent(self, event):
        # botón derecho para evitar cierre accidental con doble clic izquierdo
        if event.button() == Qt.RightButton:
            self.close()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("NOVA Widget")

    widget = NovaWidget()
    widget.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
