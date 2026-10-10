"""Short-lived input actions sent over HudiyData's existing API connection."""
import logging
import math
from queue import Empty, Full, Queue
import threading
import time


logger = logging.getLogger(__name__)


class InputActionDispatcher:
    """Bounded backlog, no retries, and no replay into a later API session.

    Client.send serializes writers with its send lock. A dedicated daemon worker
    keeps that blocking API call away from CAN input, ZMQ reception and snapshots.
    """
    def __init__(self, api, clock=time.monotonic, max_age=1.0, queue_size=16):
        self.api = api
        self.clock = clock
        self.max_age = max_age
        self.queue = Queue(maxsize=queue_size)
        self.lock = threading.Lock()
        self.client = None
        self.connected_at = 0.0
        self.stop_event = threading.Event()
        self.worker = None

    def set_client(self, client):
        with self.lock:
            self.client = client
            self.connected_at = self.clock()

    def submit(self, payload):
        if self.stop_event.is_set() or not isinstance(payload, dict):
            return False
        event = payload.get('event')
        stamp = payload.get('monotonic_timestamp')
        if (not isinstance(event, str) or not event.strip() or len(event) > 256
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp)):
            return False
        now = self.clock()
        with self.lock:
            client = self.client
            if (client is None or not getattr(client, '_connected', False)
                    or stamp < self.connected_at or not 0 <= now - stamp <= self.max_age):
                return False
            item = (client, self.connected_at, stamp, event)
        try:
            self.queue.put_nowait(item)
            return True
        except Full:
            logger.warning('Dropping Hudiy input action: queue is full')
            return False

    def dispatch_one(self, timeout=0):
        try:
            client, session, stamp, event = self.queue.get(timeout=timeout)
        except Empty:
            return False
        try:
            with self.lock:
                valid = (not self.stop_event.is_set() and self.client is client
                         and self.connected_at == session and getattr(client, '_connected', False)
                         and 0 <= self.clock() - stamp <= self.max_age)
            if not valid:
                return False
            message = self.api.DispatchAction()
            message.action = event
            client.send(self.api.MESSAGE_DISPATCH_ACTION, 0, message.SerializeToString())
            logger.info('Dispatched Hudiy input action %s', event)
            return True
        except Exception as exc:
            logger.warning('Dropping Hudiy input action %r: %s', event, exc)
            return False
        finally:
            self.queue.task_done()

    def start(self):
        def run():
            while not self.stop_event.is_set():
                self.dispatch_one(timeout=0.2)
        self.worker = threading.Thread(target=run, daemon=True, name='HUDIY_ACTION_SEND')
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.set_client(None)
        if self.worker:
            self.worker.join(timeout=0.5)
