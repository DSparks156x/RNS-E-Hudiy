"""Independent loopback manager; no CAN workers or DataView process dependency."""
from pathlib import Path
import sys
import urllib.error
import urllib.request
import json
import atexit
import signal

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, render_template
from hudiy_manager.config_store import ConfigStore
from hudiy_manager.routes import register_management_configs, register_management_metadata, register_management_services, register_management_video, register_management_rnse_bridge
from hudiy_manager.rnse_bridge import RnseBridgeClient
from hudiy_manager.service_control import ServiceController
from hudiy_manager.video_control import VideoController


def dataview_theme():
    """Use DataView's last reported palette in standalone browser previews."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:5003/api/files/theme', timeout=0.5) as response:
            data = json.loads(response.read(16384))
        from hudiy_dataview.file_portal import cache_hudiy_theme
        return data.get('theme'), cache_hudiy_theme
    except (OSError, ValueError, urllib.error.URLError):
        return None, None


def create_app(project_root=None, home=None, controller=None, theme_loader=None, metadata_path=None, video_controller=None, bridge_client=None):
    project_root = Path(project_root or Path(__file__).resolve().parents[1]).absolute()
    assets = project_root / 'hudiy_dataview'
    app = Flask(__name__, static_folder=str(assets / 'static'), template_folder=str(assets / 'templates'))
    app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024
    store = ConfigStore(project_root, home)
    controller = controller or ServiceController(home=store.home)
    video = video_controller or VideoController(home=store.home)
    app.extensions['management_config_store'] = store
    app.extensions['management_services'] = controller
    app.extensions['management_video'] = video
    atexit.register(video.close)
    register_management_configs(app, store)
    register_management_services(app, store, controller)
    register_management_metadata(app, metadata_path or assets / 'static' / 'configMetadata.json')
    register_management_video(app, store, video)
    register_management_rnse_bridge(app, store, bridge_client or RnseBridgeClient(store))

    @app.get('/')
    @app.get('/manage')
    def index():
        return render_template('manage.html')

    cached_theme = {'theme': None}
    load_theme = theme_loader or dataview_theme

    @app.get('/api/manage/theme')
    def manager_theme():
        try:
            theme, validate = load_theme()
            if theme and validate and validate(app, theme):
                cached_theme['theme'] = app.config.get('HUDIY_COLOR_SCHEME')
        except (OSError, ValueError):
            pass
        return jsonify(cached_theme)

    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app


def main():
    app = create_app()
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(_signum, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        app.run(host='127.0.0.1', port=5004, threaded=True)
    finally:
        app.extensions['management_video'].close()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    main()
