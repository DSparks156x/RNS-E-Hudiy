"""Open only the bundled calibration page in Hudiy's same-user Web Viewer."""
import hmac
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import urlencode, urlsplit

from flask import jsonify, render_template, request

from .config_store import ConfigError
from .routes import require_mutation_access
from .video_control import wayland_socket, VideoUnavailable


class PatternUnavailable(ConfigError):
    status = 503


class TestPatternWindow:
    def __init__(self, home, launcher=None, desktop=None, platform=None):
        self.home = Path(home)
        self.launcher = launcher or subprocess.Popen
        self.desktop = desktop or wayland_socket
        self.platform = sys.platform if platform is None else platform
        self._lock = threading.Lock()
        self._process = None
        self._token = None

    def _running(self):
        return self._process is not None and self._process.poll() is None

    def status(self):
        with self._lock:
            return {'running': self._running(), 'width': 800, 'height': 480}

    def valid_session(self, token):
        return isinstance(token, str) and bool(self._token) and hmac.compare_digest(self._token, token)

    def open(self):
        with self._lock:
            if self._running():
                return {'running': True, 'width': 800, 'height': 480}
            if self.platform != 'linux':
                raise PatternUnavailable('Native test pattern needs the Pi desktop. Using this browser instead.')
            viewer = self.home / '.hudiy/share/web_viewer'
            if not viewer.is_file() or not os.access(viewer, os.X_OK):
                raise PatternUnavailable('Hudiy Web Viewer is unavailable. Using this browser instead.')
            try:
                socket = Path(self.desktop())
            except VideoUnavailable as error:
                raise PatternUnavailable(str(error)) from error
            environment = dict(os.environ, XDG_RUNTIME_DIR=str(socket.parent), WAYLAND_DISPLAY=socket.name, QT_QPA_PLATFORM='wayland', QT_SCALE_FACTOR='1')
            self._token = secrets.token_urlsafe(32)
            # URL, executable and surface size are fixed; request data cannot launch another program.
            url = 'http://127.0.0.1:5004/test-pattern?' + urlencode({'session': self._token})
            try:
                self._process = self.launcher([str(viewer), '--url', url, '--width', '800', '--height', '480', '--rendering_mode', '1'], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as error:
                self._token = None
                raise PatternUnavailable('Could not open Hudiy Web Viewer. Using this browser instead.') from error
            return {'running': self._running(), 'width': 800, 'height': 480}

    def close(self, token=None):
        with self._lock:
            if token is not None and not self.valid_session(token):
                raise ConfigError('This test-pattern session has ended.')
            if self._running():
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            self._process = None
            self._token = None
            return {'running': False}


def register_test_pattern(app, store, window):
    @app.get('/test-pattern')
    def pattern_page():
        token = request.args.get('session', '')
        if not window.valid_session(token):
            return 'This test-pattern session has ended.', 410
        return render_template('rnse_test_pattern.html', session=token)

    @app.get('/api/manage/test-pattern')
    def pattern_status():
        return jsonify(window.status())

    @app.post('/api/manage/test-pattern/open')
    def pattern_open():
        denied = require_mutation_access(store)
        if denied:
            return denied
        return jsonify(window.open())

    @app.post('/api/manage/test-pattern/close')
    def pattern_close():
        token = request.headers.get('X-Hudiy-Pattern-Session')
        if token:
            # The native child has a close-only capability, never the user's portal PIN.
            origin = urlsplit(request.headers.get('Origin', ''))
            if (request.headers.get('X-Hudiy-Management') != '1'
                    or request.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site')
                    or (origin.netloc and (origin.scheme != request.scheme or origin.netloc != request.host))
                    or not window.valid_session(token)):
                return jsonify({'error': 'Test-pattern close must come from its current window.'}), 403
        else:
            denied = require_mutation_access(store)
            if denied:
                return denied
        return jsonify(window.close(token))
