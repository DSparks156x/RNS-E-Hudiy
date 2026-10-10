"""Bounded requests to the existing CAN base service; never sends CAN directly."""
import json

from .config_store import ConfigError
from .rnse_adc_protocol import validate_values

DEFAULT_ENDPOINT = 'ipc:///run/rnse_control/rnse_control.ipc'
MAX_REPLY_BYTES = 16384


class BridgeUnavailable(ConfigError):
    status = 503


class RnseBridgeClient:
    def __init__(self, store, exchange=None):
        self.store = store
        self.exchange = exchange or self._exchange

    def _exchange(self, endpoint, data):
        import zmq
        socket = zmq.Context.instance().socket(zmq.REQ)
        try:
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.SNDTIMEO, 1500)
            socket.setsockopt(zmq.RCVTIMEO, 1500)
            socket.setsockopt(zmq.IMMEDIATE, 1)
            socket.setsockopt(zmq.MAXMSGSIZE, MAX_REPLY_BYTES)
            socket.connect(endpoint)
            socket.send_json(data)
            content = socket.recv()
            if len(content) > MAX_REPLY_BYTES:
                raise BridgeUnavailable('RNS-E bridge reply exceeds the size limit.')
            return json.loads(content)
        except (zmq.ZMQError, ValueError) as error:
            raise BridgeUnavailable('RNS-E functions is unavailable. Start it in Services, then try again.') from error
        finally:
            socket.close()

    def request(self, action, values=None):
        document = self.store.read('rnse')['document']
        endpoint = document.get('interfaces', {}).get('zmq', {}).get('rnse_control_command', DEFAULT_ENDPOINT)
        # This control surface is local; a config upload cannot redirect it to a
        # remote host or expose a network command listener.
        if not isinstance(endpoint, str) or not endpoint.startswith('ipc:///') or '\x00' in endpoint:
            raise ConfigError('RNS-E bridge commands require a local absolute IPC endpoint.')
        data = {'action': action}
        if action == 'adc_write':
            try:
                data['values'] = validate_values(values)
            except ValueError as error:
                raise ConfigError(str(error)) from None
        if action == 'manual':
            if not isinstance(values, dict) or not values or set(values) - {'brightness', 'lcd_brightness'}:
                raise ConfigError('Provide brightness or lcd_brightness.')
            for name, value in values.items():
                maximum = 10 if name == 'brightness' else 100
                if type(value) is not int or not 0 <= value <= maximum:
                    raise ConfigError(f'{name} must be an integer from 0 to {maximum}.')
            data['values'] = values
        result = self.exchange(endpoint, data)
        if not isinstance(result, dict):
            raise BridgeUnavailable('RNS-E functions returned an invalid reply.')
        if result.get('error'):
            error = ConfigError if result.get('status') == 400 else BridgeUnavailable
            raise error(str(result['error']))
        return result
