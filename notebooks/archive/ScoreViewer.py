# ui/VerovioViewer.py
import base64
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from collections import deque

class ScoreViewer(QWebEngineView):
    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self._root = Path(project_root).resolve()
        self._js_ready = False
        self._pending_js = deque(maxlen=200)

        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self.loadFinished.connect(self._on_load_finished)

        html_path = self._root / "resources" / "verovio" / "viewer.html"
        self.setUrl(QUrl.fromLocalFile(str(html_path)))

    def _on_load_finished(self, ok: bool):
        if not ok:
            print("[VerovioViewer] loadFinished: FAILED")
            return

        # Confirm the JS API exists before marking ready
        def _cb(result):
            self._js_ready = bool(result)
            print(f"[VerovioViewer] JS API ready: {self._js_ready}")
            if self._js_ready:
                while self._pending_js:
                    self.page().runJavaScript(self._pending_js.popleft())

        self.page().runJavaScript("typeof window.setPlaybackTime === 'function'", _cb)

    def _run_js(self, code: str):
        if self._js_ready:
            self.page().runJavaScript(code)
        else:
            self._pending_js.append(code)

    # these need to be called after the viewer is loaded
    # otherwise will be queued
    def load_score(self, filepath: str | Path):
        p = Path(filepath)
        ext = p.suffix.lower()
        if ext not in {".musicxml", ".xml", ".mxl", ".mei"}:
            raise ValueError(f"Unsupported score file extension: {ext}")

        data = p.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        js_ext = ".mxl" if ext == ".mxl" else (".mei" if ext == ".mei" else ".xml")

        self._run_js(f'window.loadScoreBase64("{js_ext}", "{b64}");')

    def set_playback_time(self, t_sec: float):
        self._run_js(f"window.setPlaybackTime({float(t_sec):.6f});")