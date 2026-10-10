"""Local bridge requests and projection snapshots; CAN output stays in the gateway."""
import asyncio
import json
import logging
import time

import aiozmq
import zmq

logger = logging.getLogger(__name__)
MAX_COMMAND_BYTES = 4096


def parse_request(parts):
    if len(parts) != 1 or len(parts[0]) > MAX_COMMAND_BYTES:
        raise ValueError('Bridge requests must be a single JSON object of at most 4 KiB.')
    data = json.loads(parts[0].decode('utf-8'), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number.')))
    if not isinstance(data, dict) or data.get('action') not in ('status', 'manual', 'reload', 'adc_status', 'adc_write', 'adc_dump', 'adc_revert', 'adc_identify'):
        raise ValueError('Unsupported RNS-E bridge action.')
    if set(data) - ({'action', 'values'} if data['action'] in ('manual', 'adc_write') else {'action'}):
        raise ValueError('Unexpected bridge request fields.')
    return data


async def serve_commands(address, process, running):
    stream = None
    try:
        stream = await aiozmq.create_zmq_stream(zmq.REP, bind=address)
        while running():
            parts = await stream.read()
            try:
                result = process(parse_request(parts))
            except (ValueError, TypeError, OSError) as error:
                result = {'error': str(error), 'status': 400}
            except Exception:
                logger.exception('RNS-E bridge request failed')
                result = {'error': 'RNS-E bridge request failed.', 'status': 503}
            stream.write([json.dumps(result, allow_nan=False).encode('utf-8')])
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception('RNS-E bridge request endpoint stopped')
    finally:
        if stream:
            stream.close()


async def listen_projection(address, observe, running, clock=time.monotonic):
    """Lease snapshots, without mapping visibility or Bluetooth to connection."""
    stream = None
    # A policy reload can inherit a provider from the previous listener. Even
    # when no fresh publisher frame arrives, that inherited hint must expire.
    last_seen = clock()
    expired = False
    try:
        stream = await aiozmq.create_zmq_stream(zmq.SUB, connect=address)
        stream.transport.subscribe(b'HUDIY_PROJECTION')
        while running():
            # Malformed traffic must not extend a valid provider's lease.
            if not expired and clock() - last_seen > 6:
                observe(0, 'producer_unavailable'); expired = True
            try:
                parts = await asyncio.wait_for(stream.read(), timeout=2)
            except asyncio.TimeoutError:
                continue
            try:
                if len(parts) != 2 or parts[0] != b'HUDIY_PROJECTION' or len(parts[1]) > MAX_COMMAND_BYTES:
                    continue
                data = json.loads(parts[1])
                source = data.get('source')
                evidence = data.get('evidence')
                if type(source) is not int or source not in (0, 1, 2) or evidence not in ('reported_provider', 'api_disconnected', 'no_provider'):
                    continue
                last_seen = clock(); expired = False
                observe(source, evidence)
            except (ValueError, TypeError, AttributeError):
                logger.warning('Ignored invalid RNS-E source snapshot')
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception('RNS-E projection listener stopped')
        observe(0, 'producer_unavailable')
    finally:
        if stream:
            stream.close()
