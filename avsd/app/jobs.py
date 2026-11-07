"""One long operation at a time: flash, check, Teensy. Runs on its own because the screen can be down while it does."""
import json
import os
import threading
import time


class BusyError(Exception):
    pass


class Jobs:
    def __init__(self, paths, clock=time.time):
        self.paths, self.clock = paths, clock
        self.lock = threading.Lock()
        self.thread = None
        self.current = None

    def busy(self):
        with self.lock:
            return bool(self.current and self.current['state'] == 'running')

    def _save(self, job):
        temporary = str(self.paths.job) + '.tmp'
        with open(temporary, 'w') as f:
            json.dump(job, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, self.paths.job)

    def start(self, name, title, work):
        """work(log) returns a message, or raises with one."""
        with self.lock:
            if self.current and self.current['state'] == 'running':
                raise BusyError('%s is running.' % self.current['title'])
            job = {'name': name, 'title': title, 'state': 'running', 'message': '', 'lines': [], 'started': self.clock(), 'finished': None}
            self.current = job
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        path = self.paths.logs / ('%s-%s.log' % (time.strftime('%Y%m%d-%H%M%S'), name))
        handle = open(path, 'a')

        def log(line):
            with self.lock:
                job['lines'].append(line)
            handle.write('%s %s\n' % (time.strftime('%H:%M:%S'), line))
            handle.flush()
            os.fsync(handle.fileno())

        def run():
            try:
                message = work(log) or 'Done.'
                state = 'ok'
            except Exception as error:      # everything ends up on the screen and in the log
                message = str(error) or type(error).__name__
                state = 'failed'
            log(message)
            with self.lock:
                job.update(state=state, message=message, finished=self.clock())
            handle.close()
            self._save(job)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return job

    def snapshot(self):
        with self.lock:
            if self.current:
                return dict(self.current, lines=list(self.current['lines']))
        try:
            with open(self.paths.job) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
