#!/usr/bin/env python3
"""A/V over SD settings and update app. Needs only Flask, and imports nothing from the rest of the repo.

Everyone on the Pi's network can read: a phone watches a flash here while the car's screen is down.
Only Hudiy on the Pi itself can change anything.
"""
import ipaddress
import os
import re
import socket
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import can_link
import chain as chain_module
import jobs as jobs_module
import operations
import rnse_flash
import settings_store

PORT = 5005
PORTAL_PORT = 5003
RNSE_OPS = {'check': 'Check against file', 'rehearse': 'Dry run', 'flash': 'Flash RNS-E', 'decoder': 'Read decoder version'}


def portal_urls(run=subprocess.run):
    """File portal addresses, if DataView is on this Pi. Standalone installs have none."""
    try:
        with socket.create_connection(('127.0.0.1', PORTAL_PORT), timeout=0.2):
            pass
        out = run(['ip', '-4', '-o', 'addr', 'show', 'scope', 'global'], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = re.findall(r'^\d+:\s+(\S+)\s+inet\s+([\d.]+)/', out, re.MULTILINE)
    found.sort(key=lambda item: not item[0].startswith('wl'))
    return ['http://%s:%d/files' % (address, PORTAL_PORT) for _, address in found]


def create_app(home=None, chain=None, jobs=None, rnse=None, teensy=None, releases=None, updater=operations.start_update, can=can_link.can_state, background=False):
    app = Flask(__name__, static_folder=os.path.join(HERE, 'static'), template_folder=os.path.join(HERE, 'templates'))
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    paths = chain_module.Paths(home)
    chain = chain or chain_module.Chain(paths)
    settings = settings_store.SettingsStore(paths, chain)
    jobs = jobs or jobs_module.Jobs(paths)
    rnse = rnse or operations.RnseOperations(paths, chain, HERE)
    teensy = teensy or operations.TeensyUpdate(paths, chain)
    releases = releases or operations.Releases(paths, chain)
    app.extensions['avsd_settings'] = settings

    def is_local():
        try:
            return ipaddress.ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            return False

    @app.before_request
    def guard():
        if request.method == 'GET':
            return None
        # The header stops a web page in the same browser from posting here.
        if not is_local() or request.headers.get('X-AVSD') != '1':
            return jsonify({'error': 'Change this from the car. Other devices can only watch.'}), 403
        return None

    def refuse_when_busy():
        if jobs.busy():
            return jsonify({'error': 'Wait for the running operation to finish.'}), 409
        return None

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def status():
        return jsonify({
            'chain': chain.status(),
            'can': can(),
            'teensy': teensy.status(),
            'releases': releases.status(),
            'decoder': rnse.decoder(),
            'portal': portal_urls(),
            'firmware_dir': str(paths.firmware),
            'can_change': is_local(),
        })

    @app.get('/api/job')
    def job():
        return jsonify({'job': jobs.snapshot()})

    @app.get('/api/settings')
    def settings_get():
        return jsonify(settings.snapshot())

    def settings_action(action):
        blocked = refuse_when_busy()
        if blocked:
            return blocked
        try:
            return jsonify(action())
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

    @app.post('/api/settings')
    def settings_apply():
        return settings_action(lambda: settings.apply((request.get_json(silent=True) or {}).get('values')))

    @app.post('/api/settings/save')
    def settings_save():
        return settings_action(lambda: settings.save((request.get_json(silent=True) or {}).get('values')))

    @app.post('/api/settings/defaults')
    def settings_defaults():
        return settings_action(settings.restore_defaults)

    @app.post('/api/chain')
    def chain_action():
        blocked = refuse_when_busy()
        if blocked:
            return blocked
        action = (request.get_json(silent=True) or {}).get('action')
        if action not in ('start', 'stop', 'restart'):
            return jsonify({'error': 'Unknown action.'}), 400
        getattr(chain, action)()
        return jsonify({'ok': True})

    @app.get('/api/logs')
    def logs():
        source = request.args.get('source', 'live')
        lines = max(1, min(request.args.get('lines', 200, type=int), 2000))
        try:
            return jsonify({'lines': chain.log_lines(source, lines)})
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

    @app.get('/api/firmware')
    def firmware():
        return jsonify({'files': operations.firmware_files(paths)})

    def start_job(name, title, work):
        try:
            jobs.start(name, title, work)
        except jobs_module.BusyError as error:
            return jsonify({'error': str(error)}), 409
        return jsonify({'job': jobs.snapshot()}), 202

    @app.post('/api/rnse')
    def rnse_op():
        data = request.get_json(silent=True) or {}
        op = data.get('op')
        if op not in RNSE_OPS:
            return jsonify({'error': 'Unknown operation.'}), 400
        names = data.get('files', [])
        reason = can_link.not_ready_reason(can())
        if reason:
            return jsonify({'error': reason}), 409
        try:
            if op != 'decoder':
                rnse_flash.load_targets(operations.safe_firmware_paths(paths, names))
        except rnse_flash.FlashError as error:
            return jsonify({'error': str(error)}), 400
        return start_job('rnse-' + op, RNSE_OPS[op], lambda log: rnse.run(op, names, log))

    @app.post('/api/unit/counters')
    def unit_counters():
        blocked = refuse_when_busy()
        if blocked:
            return blocked
        try:
            return jsonify(rnse.counters())
        except (rnse_flash.FlashError, can_link.UnitError) as error:
            return jsonify({'error': str(error)}), 409

    @app.post('/api/teensy/flash')
    def teensy_flash():
        return start_job('teensy', 'Flash Teensy', teensy.flash)

    @app.post('/api/update')
    def update():
        blocked = refuse_when_busy()
        if blocked:
            return blocked
        if releases.updates_with_rnse():
            return jsonify({'error': 'Use Update RNS-E in the Hudiy menu. It updates this too.'}), 409
        script = paths.current / 'update_avsd.sh'
        try:
            updater(script)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            return jsonify({'error': str(error)}), 500
        return jsonify({'ok': True})

    @app.post('/api/rollback')
    def rollback():
        blocked = refuse_when_busy()
        if blocked:
            return blocked
        try:
            releases.rollback()
        except (OSError, ValueError) as error:
            return jsonify({'error': str(error)}), 400
        return jsonify({'ok': True})

    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    if background:
        def housekeeping():
            started = time.time()
            watching = True
            while True:
                try:
                    if watching:
                        restarts = sum('avsd: restart:' in line for line in chain.journal(60))
                        watching = not releases.watch_step(started, chain.status(), restarts)
                except Exception as error:      # this loop must outlive any one bad read
                    print('avsd-app housekeeping: %s' % error, flush=True)
                time.sleep(1)
        threading.Thread(target=housekeeping, daemon=True).start()
    return app


if __name__ == '__main__':
    create_app(background=True).run(host='0.0.0.0', port=PORT, threaded=True)
