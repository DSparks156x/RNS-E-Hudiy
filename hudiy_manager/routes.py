"""Management APIs shared by the local manager and network file portal."""
import hmac
import json
from pathlib import Path
from urllib.parse import urlsplit

from flask import jsonify, request

from .config_store import ConfigError, MAX_CONFIG_BYTES, parse_document


def require_mutation_access(store):
    # Custom headers cannot be sent by a cross-origin HTML form, and these APIs
    # do not grant CORS access. Also reject explicit foreign browser origins.
    if request.headers.get('X-Hudiy-Management') != '1':
        return jsonify({'error': 'Management requests need the management header.'}), 403
    origin = request.headers.get('Origin')
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != request.scheme or parsed.netloc != request.host:
            return jsonify({'error': 'Management changes must come from this app.'}), 403
    if request.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
        return jsonify({'error': 'Management changes must come from this app.'}), 403
    pin = store.pin()
    if pin and not hmac.compare_digest(pin, request.headers.get('X-Hudiy-Pin', '')):
        return jsonify({'error': 'The portal PIN is incorrect.'}), 403
    return None


def register_management_configs(app, store):
    """Expose exactly the same replacement rules to DataView's upload picker."""
    @app.errorhandler(ConfigError)
    def configuration_error(error):
        return jsonify({'error': str(error)}), error.status

    @app.get('/api/manage/configs')
    def manager_configs():
        return jsonify({'configs': store.list(), 'pin_required': bool(store.pin())})

    @app.get('/api/manage/configs/<target_id>')
    def manager_config(target_id):
        return jsonify(store.read(target_id))

    @app.put('/api/manage/configs/<target_id>')
    def manager_save(target_id):
        denied = require_mutation_access(store)
        if denied:
            return denied
        if request.content_length is not None and request.content_length > MAX_CONFIG_BYTES:
            return jsonify({'error': 'Configuration exceeds the 2 MiB limit.'}), 413
        data = parse_document(request.stream.read(MAX_CONFIG_BYTES + 1))
        if not isinstance(data, dict) or 'document' not in data:
            raise ConfigError('Provide a document and its current revision.')
        return jsonify(store.save(target_id, data['document'], data.get('revision')))

    @app.post('/api/manage/configs/<target_id>/import')
    def manager_import(target_id):
        denied = require_mutation_access(store)
        if denied:
            return denied
        store.target(target_id)
        if request.content_length is not None and request.content_length > MAX_CONFIG_BYTES + 65536:
            return jsonify({'error': 'Configuration exceeds the 2 MiB limit.'}), 413
        file = request.files.get('file')
        if not file or not file.filename:
            raise ConfigError('Choose a JSON configuration file.')
        # Uploaded filenames never determine a path. The picker chooses a named
        # target, and content validation determines whether the file fits it.
        content = file.stream.read(MAX_CONFIG_BYTES + 1)
        document = parse_document(content)
        return jsonify(store.save(target_id, document, request.form.get('revision')))


def register_management_services(app, store, controller):
    @app.get('/api/manage/services')
    def manager_services():
        return jsonify({'services': controller.list()})

    @app.post('/api/manage/services/<service_id>/<action>')
    def manager_service_action(service_id, action):
        denied = require_mutation_access(store)
        if denied:
            return denied
        return jsonify(controller.action(service_id, action))

    @app.get('/api/manage/services/<service_id>/logs')
    def manager_service_logs(service_id):
        try:
            lines = int(request.args.get('lines', '100'))
        except (TypeError, ValueError):
            raise ConfigError('Log line count must be between 1 and 500.') from None
        return jsonify(controller.logs(service_id, lines))


def register_management_metadata(app, metadata_path):
    @app.get('/api/manage/metadata')
    def manager_metadata():
        try:
            document = json.loads(Path(metadata_path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return jsonify({'schema': {}, 'sections': [], 'error': 'Setting descriptions have not been installed.'}), 503
        return jsonify(document)
