"""Full production DisplayEngine, with bench-only controls on its own thread.

No --mock, fake READY, fake ACK, CAN adapter, or replacement renderer here.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(args.repo / 'dis_client'),str(args.repo/'rns-e_can'), str(args.repo)]
    import zmq
    # Bench phone actions must never create a host keyboard device.
    sys.modules['uinput'] = None
    import dis_display
    from wheel_controls import WheelControlRouter
    # Keep the user's saved settings separate, even on Windows or Linux.
    dis_display.SETTINGS_FILE = str(args.runtime / 'display_settings.json')

    class BenchEngine(dis_display.DisplayEngine):
        def __init__(self):
            super().__init__(str(args.config), mock=False)
            self.control = self.zmq_ctx.socket(zmq.PULL)
            self.control.setsockopt(zmq.LINGER, 0)
            self.control.connect(self.cfg['bench_control'])
            # A socket polled here still wakes the actual production loop.
            self.poller.register(self.control, zmq.POLLIN)
            self.bench_applied = 0
            self.bench_errors = []
            self.bench_normal_inputs = []
            self.bench_wheel = WheelControlRouter(self._wheel_emit,self._normal_input,
                double_click_ms=self.cfg.get('input_mappings',{}).get('mfsw',{}).get('double_click_ms',350),
                long_count=self.cfg.get('input_mappings',{}).get('mmi',{}).get('long_press_message_count',5))
            owner=self
            class ErrorTelemetry(logging.Handler):
                def emit(self,record):
                    if record.levelno>=logging.ERROR:
                        owner.bench_errors.append(self.format(record)[-1200:])
                        del owner.bench_errors[:-8]
            logging.getLogger().addHandler(ErrorTelemetry())

        def _normal_input(self,event):
            # The Pi/HUDIY keyboard sink is intentionally inert on the bench.
            self.bench_normal_inputs.append(dict(event=event,time=__import__('time').time()))
            del self.bench_normal_inputs[:-8]

        def _wheel_emit(self,event,owner,app):
            data=dict(app=app,control_epoch=self._wheel_epoch,owner=owner,event=event)
            self._handle_wheel_input(b'WHEEL_CONTROL' if event=='mode' else b'DIS_INPUT',data)

        def _wheel_context(self):
            app=next(k for k,v in self.apps.items() if v is self.current_app)
            self.bench_wheel.context(app,self.service_ready and not self.user_paused,
                context_id=self._wheel_epoch,controllable=hasattr(self.current_app,'set_control_mode'))

        def publish_status(self, force=False):
            super().publish_status(force=force)
            pending = getattr(self, '_pending_ui_frame', None)
            status=dict(
                applied=getattr(self,'bench_applied',0), pending_seq=pending[0] if pending else None,
                paused=getattr(self,'user_paused',False),errors=getattr(self,'bench_errors',[]))
            wheel=getattr(self,'bench_wheel',None)
            if wheel is not None:
                status['wheel']=dict(owner=wheel.owner,supported=wheel.supported,
                    pending=list(wheel.pending),normal_inputs=self.bench_normal_inputs)
            signature=json.dumps(status)
            if force or signature!=getattr(self,'_last_bench_status',None):
                self.pub_status.send_multipart([b'BENCH_ENGINE_STATUS',signature.encode()])
                self._last_bench_status=signature

        def _apply_data(self, topic, data):
            # Match the production run-loop dispatch and keep its actual app
            # callbacks and policies. Ordered control + data avoids drawing a
            # new page before its callback has arrived on another PUB socket.
            topic = topic.encode()
            if topic == b'HUDIY_NAV_STATUS':
                self.apps['app_nav'].update_hudiy(topic,data)
                self.nav_active = data.get('active') is True
                self._handle_nav_auto_switch(self.apps['app_nav'])
            elif topic.startswith(b'HUDIY_NAV'):
                self.apps['app_nav'].update_hudiy(topic,data)
                if topic == b'HUDIY_NAV':
                    # A full manual bench maneuver is one route transaction:
                    # supply the producer's separate active-status callback
                    # as well. Keep the real availability gate in force.
                    self.nav_active = self.apps['app_nav'].has_route
                    self.apps['app_nav'].update_hudiy(b'HUDIY_NAV_STATUS',dict(active=self.nav_active))
                self._handle_nav_auto_switch(self.apps['app_nav'])
            elif topic == b'HUDIY_PHONE':
                self.apps['app_phone'].update_hudiy(topic,data)
                # Manual bench page choice takes priority over phone overlays.
                # Still exercise the real PhoneApp state/rendering/inputs.
            elif topic == b'HUDIY_MEDIA':
                self.apps['app_media'].update_hudiy(topic,data)
                self._handle_media_match(data)
            elif topic == b'HUDIY_OPENPILOT':
                self.apps['app_openpilot'].update_hudiy(topic,data)
            elif topic == b'HUDIY_COVERART':
                self.apps['app_coverart'].update_hudiy(topic,data)
            if topic in (b'HUDIY_VALUES',b'HUDIY_DIAG'):
                self.apps['app_car_info'].update_hudiy(topic,data)
            if self.current_app and not (topic in (b'HUDIY_VALUES',b'HUDIY_DIAG') and self.current_app is self.apps['app_car_info']):
                self.current_app.update_hudiy(topic,data)

        def _handle_ui_frame_result(self,seq,success):
            pending=getattr(self,'_pending_ui_frame',None)
            if (not success and pending is not None and pending[0]==seq
                    and pending[1] is self.current_app):
                self.user_paused=True
            handled=super()._handle_ui_frame_result(seq,success)
            if handled and not success:
                # A rejected scene needs operator attention, not an endless
                # production retry loop against the same invalid data.
                self.user_paused=True
                self.bench_errors.append(f'DRAW_NACK {seq}; drawing held. Send corrected data or select a page to retry.')
                del self.bench_errors[:-8]
                self.publish_status(force=True)
            return handled

        def _draw(self):
            # Controls execute on the same thread as production app state and
            # sockets. Never let an HTTP worker mutate the engine or draw.
            for _ in range(32):
                if not self.control.poll(0):
                    break
                action = self.control.recv_json()
                kind = action.get('action')
                if kind in ('data','page','config','input') and self.service_ready:
                    self.user_paused=False
                if kind == 'data':
                    self._apply_data(action['topic'],action['payload'])
                elif kind == 'can':
                    # Feed the real receive handler via a one-message adapter;
                    # this never sends a frame on the physical CAN bus.
                    original=self.sub
                    message=[f"CAN_0x{action['can_id']:X}".encode(),json.dumps(dict(data_hex=action['data_hex'])).encode()]
                    class Fixture:
                        def recv_multipart(self,flags=0):
                            nonlocal message
                            if message is None:raise zmq.Again()
                            result=message;message=None;return result
                    try:
                        self.sub=Fixture();self._handle_can()
                    finally:self.sub=original
                elif kind == 'page' and action['page'] in self.pages:
                    self._cancel_auto_switches()
                    self.switch_to_app(action['page'])
                elif kind == 'input':
                    event = action['event']
                    self._wheel_context()
                    if event in ('stalk_up','stalk_down'):
                        name=event[6:];now=__import__('time').time()
                        self._btn_event(name,True,now);self._btn_event(name,False,now+.01)
                    elif event in ('wheel_up','wheel_down'):
                        self.bench_wheel.handle('scroll_up' if event=='wheel_up' else 'scroll_down')
                        self.bench_wheel.handle('release')
                    else:
                        button='mode' if event.startswith('wheel_mode') else 'click'
                        presses=self.bench_wheel.long_count if event.endswith('_hold') else 1
                        repeats=2 if event.endswith('_double') else 1
                        for _ in range(repeats):
                            for _ in range(presses):self.bench_wheel.handle(button)
                            self.bench_wheel.handle('release')
                elif kind == 'config':
                    center = self.cfg['display']['center_display']
                    center['high_resolution'] = action['high_resolution']
                    center['navigation']['icon_style'] = action['icon_style']
                    center['navigation']['approach_bar_max_distance'] = action['approach_bar_max_distance']
                    self.force_redraw(send_clear=False)
                elif kind == 'workspace':
                    readings=self.apps.get('app_car_info')
                    if hasattr(readings,'last_config_check'):
                        readings.last_config_check=-10;readings.tick()
                    self.force_redraw(send_clear=False)
                elif kind == 'shutdown':
                    self.running = False
                    return
                self.bench_applied = action.get('id',self.bench_applied)
            self._wheel_context()
            self.bench_wheel.tick()
            if __import__('time').monotonic()-getattr(self,'_bench_wheel_heartbeat',0)>.5:
                self.bench_wheel.heartbeat()
                self._bench_wheel_heartbeat=__import__('time').monotonic()
            super()._draw()
            self.publish_status()

    engine = None
    try:
        engine = BenchEngine()
        engine.run()
    finally:
        if engine is not None:
            for sock in (engine.sub, engine.sub_hudiy, engine.draw, engine.sub_status,
                         engine.pub_status, engine.control, getattr(engine, 'tp2_cmd', None)):
                if sock is not None:
                    sock.close(linger=0)
            for app in engine.apps.values():
                logger=getattr(app,'logger',None)
                if logger is not None and hasattr(logger,'close'):logger.close()
            engine.zmq_ctx.term()


if __name__ == '__main__':
    main()
