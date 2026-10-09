"""Same-user Wayland output colour controls, owned by one worker thread.

The project config is untouched. Live changes last while this process owns the
gamma control; only an explicit save writes a separate startup profile.
"""
from concurrent.futures import Future, TimeoutError
import copy
import json
import os
from pathlib import Path
import queue
import stat
import sys
import tempfile
import threading
import time

from .pi_wayland_color import ColorSettings, WaylandSession, finite_bound, choose_output


DEFAULT_SETTINGS = dict(gamma=1.0, contrast=1.0, black_point=0.0,
                        gain_r=1.0, gain_g=1.0, gain_b=1.0)
RANGES = dict(gamma=(.5, 2.0), contrast=(.5, 1.5), black_point=(0.0, .10),
              gain_r=(.5, 1.5), gain_g=(.5, 1.5), gain_b=(.5, 1.5))
MAX_PROFILE_BYTES = 8192


class VideoError(ValueError):
    status = 400


class VideoUnavailable(VideoError):
    status = 503


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULT_SETTINGS):
        raise VideoError('Provide gamma, contrast, black_point, gain_r, gain_g and gain_b.')
    try:
        return {name: finite_bound(name, settings[name], *limits)
                for name, limits in RANGES.items()}
    except ValueError as error:
        raise VideoError(str(error)) from None


def native_settings(settings):
    return ColorSettings(settings['gamma'], settings['contrast'], settings['black_point'],
                         (settings['gain_r'], settings['gain_g'], settings['gain_b']))


def wayland_socket(environ=None, uid=None, platform=None):
    """Select an existing desktop-user socket without altering global env vars."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform != 'linux':
        raise VideoUnavailable('Pi video controls require a Linux Wayland desktop.')
    uid = os.geteuid() if uid is None else uid
    if uid == 0:
        raise VideoUnavailable('Run video controls as the Hudiy desktop user, not root.')
    runtime = Path(environ.get('XDG_RUNTIME_DIR') or f'/run/user/{uid}').absolute()
    try:
        info = runtime.lstat()
    except OSError:
        raise VideoUnavailable('The desktop runtime directory is not available yet.') from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
            info.st_mode & 0o022 or runtime.resolve() != runtime):
        raise VideoUnavailable('The desktop runtime directory must belong to this user and not be writable by others.')

    def owned_socket(path):
        try:
            info = path.lstat()
        except OSError:
            return False
        return stat.S_ISSOCK(info.st_mode) and info.st_uid == uid and path.parent == runtime

    requested = environ.get('WAYLAND_DISPLAY')
    if requested:
        display = Path(requested)
        path = display if display.is_absolute() else runtime / display
        if path.parent != runtime or not owned_socket(path):
            raise VideoUnavailable('WAYLAND_DISPLAY does not name an existing socket owned by this desktop user.')
        return str(path)
    matches = sorted(path for path in runtime.iterdir()
                     if path.name.startswith('wayland-') and path.name[8:].isdigit() and owned_socket(path))
    if len(matches) != 1:
        raise VideoUnavailable('Set WAYLAND_DISPLAY to the desktop socket; automatic discovery requires exactly one owned wayland-N socket.')
    return str(matches[0])


class VideoController:
    """Serialized libwayland actor; request threads never touch native proxies."""
    def __init__(self, home=None, session_factory=None, environment=None,
                 retry_delays=(1.0, 2.0, 5.0, 10.0, 30.0), request_timeout=6.0):
        self.home = Path(home or Path.home()).absolute()
        self.profile_path = self.home / '.hudiy' / 'share' / 'video-color.json'
        self._factory = session_factory or (lambda display: WaylandSession(display_name=display))
        self._environment = environment or wayland_socket
        self._retry_delays = tuple(retry_delays)
        if not self._retry_delays or any(delay <= 0 for delay in self._retry_delays):
            raise ValueError('Retry delays must be positive.')
        self._timeout = request_timeout
        self._commands = queue.Queue(maxsize=32)
        self._closed = False
        self._close_lock = threading.Lock()
        self._session = None
        self._desired = None
        self._retry_at = None
        self._retry_index = 0
        self._state = dict(available=False, status='unavailable', error=None, outputs=[],
                           gamma_protocol=False, active=False, output=None,
                           settings=DEFAULT_SETTINGS.copy(), saved_profile=None,
                           profile_path=str(self.profile_path), profile_error=None)
        self._thread = threading.Thread(target=self._run, name='hudiy-video-wayland', daemon=True)
        self._thread.start()

    def _call(self, operation, *args):
        if self._closed:
            raise VideoUnavailable('Video controls have stopped.')
        future = Future()
        try:
            self._commands.put_nowait((future, operation, args))
        except queue.Full:
            raise VideoUnavailable('Video controls are busy; try again shortly.') from None
        try:
            return future.result(timeout=self._timeout)
        except TimeoutError:
            future.cancel()  # A queued command must not run after its caller times out.
            raise VideoUnavailable('The Wayland operation has not completed. Refresh status before trying again.') from None

    def snapshot(self):
        return self._call('snapshot')

    def apply(self, settings, output=None):
        return self._call('apply', validate_settings(settings), self._validate_output(output))

    def save_profile(self, settings, output=None):
        return self._call('save_profile', validate_settings(settings), self._validate_output(output))

    def reset(self):
        """Restore the compositor table now and remove the saved startup profile."""
        return self._call('reset')

    @staticmethod
    def _validate_output(output):
        if output is not None and (not isinstance(output, str) or not output or len(output) > 256):
            raise VideoError('Choose an exact output identifier from the available outputs.')
        return output

    def close(self):
        """Idempotent shutdown; the worker releases its native control itself."""
        with self._close_lock:
            if not self._closed:
                self._closed = True
                try:
                    self._commands.put_nowait((None, 'close', ()))
                except queue.Full:
                    pass  # The closed flag also wakes termination after a command.
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=self._timeout)

    stop = close

    def _copy(self):
        return copy.deepcopy(self._state)

    def _open(self):
        session = self._factory(self._environment())
        try:
            inventory = session.discover()  # No gamma control during discovery.
        except Exception:
            try:
                session.close()
            except Exception:
                pass
            raise
        self._state.update(outputs=inventory['outputs'], gamma_protocol=bool(inventory['gamma_protocol']),
                           available=bool(inventory['gamma_protocol'] and inventory['outputs']),
                           status=('ready' if inventory['outputs'] else 'no_output') if inventory['gamma_protocol'] else 'unsupported',
                           error=None)
        if not inventory['gamma_protocol']:
            self._state['error'] = 'The compositor does not support wlr-gamma-control-v1.'
        elif self._state['profile_error']:
            self._state['error'] = self._state['profile_error']
        elif not inventory['outputs']:
            self._state['error'] = 'No Wayland display outputs are available.'
        return session

    def _refresh(self):
        if self._session:
            self._state['outputs'] = [output.info() for output in self._session.outputs if not output.removed]
            return self._copy()
        session = None
        try:
            session = self._open()
        except Exception as error:
            self._mark_unavailable(error)
        finally:
            if session:
                try:
                    session.close()
                except Exception as error:
                    self._mark_unavailable(error)
        return self._copy()

    def _release(self):
        session, self._session = self._session, None
        self._state['active'] = False
        if session:
            session.close()

    def _mark_unavailable(self, error):
        self._state.update(available=False, active=False, status='unavailable', error=str(error))

    def _schedule_retry(self):
        self._retry_at = time.monotonic() + self._retry_delays[min(self._retry_index, len(self._retry_delays)-1)]
        self._retry_index += 1

    def _apply(self, settings, requested, retry=False):
        session = self._session
        if session:
            try:
                chosen = choose_output(session.outputs, requested)
            except ValueError as error:
                # An invalid selector must not revoke an otherwise valid control.
                raise VideoError(str(error)) from None
        try:
            if session:
                if chosen is not session.selected:
                    self._release()
                    session = None
            if session is None:
                session = self._open()
                chosen = choose_output(session.outputs, requested)
                if not self._state['gamma_protocol']:
                    raise VideoUnavailable(self._state['error'])
                session.apply(chosen.identifier, native_settings(settings))
                self._session = session
            else:
                session.update_settings(native_settings(settings))
            # Only publish applied values after the compositor roundtrip succeeds.
            self._state.update(available=True, active=True, status='active', error=None,
                               output=chosen.identifier, settings=settings.copy())
            self._desired = dict(output=chosen.identifier, settings=settings.copy())
            self._retry_at = None
            self._retry_index = 0
            return self._copy()
        except Exception as error:
            if session:
                try:
                    session.close()
                except Exception:
                    pass
            self._session = None
            self._mark_unavailable(error)
            if self._desired:
                self._schedule_retry()
            if retry:
                return self._copy()
            if isinstance(error, VideoError):
                raise error
            if isinstance(error, ValueError):
                raise VideoError(str(error)) from None
            raise VideoUnavailable(str(error)) from None

    def _safe_profile_parent(self, create=True):
        for path in (self.profile_path, *self.profile_path.parents):
            if path.is_symlink():
                raise VideoError('The video profile cannot use symbolic links.')
        if create:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_profile(self, profile):
        self._safe_profile_parent()
        descriptor, temporary = tempfile.mkstemp(prefix='.video-color-', dir=self.profile_path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(dict(version=1, **profile), stream, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.profile_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load_profile(self):
        if not self.profile_path.exists():
            return
        try:
            self._safe_profile_parent()
            with self.profile_path.open('rb') as stream:
                content = stream.read(MAX_PROFILE_BYTES + 1)
            if len(content) > MAX_PROFILE_BYTES:
                raise VideoError('Saved video profile is too large.')
            profile = json.loads(content)
            if not isinstance(profile, dict) or profile.get('version') != 1:
                raise VideoError('Saved video profile version is unsupported.')
            selected = self._validate_output(profile.get('output'))
            if selected is None:
                raise VideoError('Saved video profile needs an exact output identifier.')
            self._desired = dict(output=selected, settings=validate_settings(profile.get('settings')))
            self._state['saved_profile'] = copy.deepcopy(self._desired)
            self._retry_at = time.monotonic()
        except (OSError, ValueError) as error:
            self._state['profile_error'] = f'Saved video profile was not loaded: {error}'
            self._mark_unavailable(error)

    def _execute(self, operation, args):
        if operation == 'snapshot':
            return self._refresh()
        if operation == 'apply':
            return self._apply(*args)
        if operation == 'save_profile':
            settings, requested = args
            session = None
            try:
                session = self._session or self._open()
                selected = choose_output(session.outputs, requested)
                if not self._state['gamma_protocol']:
                    raise VideoUnavailable(self._state['error'])
                profile = dict(output=selected.identifier, settings=settings.copy())
                self._write_profile(profile)
                self._state['saved_profile'] = profile
                self._state['profile_error'] = None
                return self._copy()
            except ValueError as error:
                if isinstance(error, VideoError):
                    raise
                raise VideoError(str(error)) from None
            except Exception as error:
                raise VideoUnavailable(f'Cannot save the video startup profile: {error}') from None
            finally:
                if session and session is not self._session:
                    session.close()
        if operation == 'reset':
            self._desired = None
            self._retry_at = None
            errors = []
            try:
                self._release()
            except Exception as error:
                errors.append(f'Output control cleanup failed: {error}')
            try:
                self._safe_profile_parent(create=False)
                self.profile_path.unlink(missing_ok=True)
                self._state['saved_profile'] = None
                self._state['profile_error'] = None
            except (OSError, ValueError) as error:
                errors.append(f'Cannot remove the startup profile; it may return after restart: {error}')
            self._state.update(output=None, settings=DEFAULT_SETTINGS.copy(), error=None)
            if errors:
                self._state['error'] = ' '.join(errors)
                raise VideoUnavailable(self._state['error'])
            return self._refresh()
        raise VideoError('Unknown video operation.')

    def _run(self):
        try:
            self._load_profile()
            while True:
                if self._closed:
                    return
                try:
                    future, operation, args = self._commands.get(timeout=.05)
                except queue.Empty:
                    future = operation = args = None
                if operation == 'close':
                    return
                if future and future.set_running_or_notify_cancel():
                    try:
                        future.set_result(self._execute(operation, args))
                    except Exception as error:
                        future.set_exception(error)
                if self._session:
                    try:
                        self._session.pump(0)
                    except Exception as error:
                        try:
                            self._release()
                        except Exception:
                            pass
                        self._mark_unavailable(error)
                        if self._desired:
                            self._schedule_retry()
                if self._desired and not self._session and self._retry_at is not None and time.monotonic() >= self._retry_at:
                    self._apply(self._desired['settings'], self._desired['output'], retry=True)
        finally:
            try:
                self._release()
            except Exception:
                pass
            while True:
                try:
                    future, _, _ = self._commands.get_nowait()
                except queue.Empty:
                    break
                if future and future.set_running_or_notify_cancel():
                    future.set_exception(VideoUnavailable('Video controls have stopped.'))
