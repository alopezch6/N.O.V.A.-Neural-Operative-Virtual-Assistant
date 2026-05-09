"""
NOVA — Boot video
Lanza el video de arranque a pantalla completa y espera a que termine.
"""
import subprocess
import threading
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
_VIDEO_DEFAULT = _BASE / "escalado" / "jarvis.mp4"

_VLC_PATHS = [
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    "vlc",
]


def _lanzar_vlc(ruta: Path, bloqueante: bool):
    for exe in _VLC_PATHS:
        try:
            proc = subprocess.Popen(
                [exe, "--fullscreen", "--play-and-exit",
                 "--no-video-title-show", "--no-osd", str(ruta)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if bloqueante:
                proc.wait()
            else:
                threading.Thread(target=proc.wait, daemon=True).start()
            return True
        except (FileNotFoundError, OSError):
            continue
    return False


def _lanzar_cv2(ruta: Path):
    """Fallback sin audio usando OpenCV."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(ruta))
        cv2.namedWindow("NOVA", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("NOVA", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        delay = max(1, int(1000 / fps))
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            cv2.imshow("NOVA", frame)
            if cv2.waitKey(delay) & 0xFF == 27:  # ESC para saltar
                break
        cap.release()
        cv2.destroyAllWindows()
    except Exception:
        pass


def reproducir_boot_video(ruta_video=None, bloqueante=True):
    """
    Lanza el video de arranque a pantalla completa.
    bloqueante=True  → bloquea hasta que el video termina (uso normal en arranque).
    bloqueante=False → lanza en segundo plano y retorna inmediatamente.
    """
    ruta = Path(ruta_video) if ruta_video else _VIDEO_DEFAULT
    if not ruta.exists():
        return

    if not _lanzar_vlc(ruta, bloqueante):
        _lanzar_cv2(ruta)
