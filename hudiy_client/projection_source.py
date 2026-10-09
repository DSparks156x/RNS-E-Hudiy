"""Provider hints for optional RNS-E source labels, not connection detection.

Hudiy's ProjectionStatus.active describes visibility. The public API has no
provider connection event, so media/navigation sources are explicitly inferred.
"""
import threading
import time


class ProjectionSource:
    def __init__(self):
        self._lock = threading.RLock()
        self._api_connected = False
        self._reports = {}
        self._sequence = 0

    def set_api_connected(self, connected):
        """A new API session must never inherit provider hints from the old one."""
        with self._lock:
            self._api_connected = bool(connected)
            self._reports.clear()
            self._sequence = 0

    def report(self, channel, provider):
        if channel not in ('media', 'navigation'):
            raise ValueError('Unknown provider channel')
        with self._lock:
            self._sequence += 1
            # Hudiy source 1=AA, 2=Autobox; the RNS-E command reverses those IDs.
            source = {1: 2, 2: 1}.get(provider, 0)
            self._reports[channel] = (self._sequence, source)

    def snapshot(self):
        with self._lock:
            providers = [(sequence, source) for sequence, source in self._reports.values()
                         if source]
            source = max(providers)[1] if self._api_connected and providers else 0
            return {
                'source': source,
                'connection_known': False,
                'evidence': ('api_disconnected' if not self._api_connected else
                             'reported_provider' if source else 'no_provider'),
                'timestamp': time.time(),
            }
