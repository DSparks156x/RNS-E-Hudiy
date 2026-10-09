"""Offline input validation, ordering and deterministic routine controls."""
import copy
from pathlib import Path
import unittest
import server


class Sink:
    def __init__(self):self.messages=[]
    def send_json(self,value):self.messages.append(copy.deepcopy(value))


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        cfg={'display':{'center_display':{'high_resolution':True,'navigation':{}}}}
        self.bridge=server.Bridge(cfg,Path('.'))
    def test_ordered_complete_data_and_page(self):
        sink=Sink()
        actions=[dict(action='data',topic='HUDIY_NAV',payload=dict(maneuver_type=4,description='ROAD',distance='300 m')),
                 dict(action='page',page='app_nav')]
        for action in actions:self.bridge.apply(server.validate(action),None,sink)
        self.assertEqual([m['action'] for m in sink.messages],['data','page'])
        self.assertEqual([m['id'] for m in sink.messages],[1,2])
    def test_manual_stops_routine(self):
        self.bridge.apply(dict(action='routine',name='mixed'),None,Sink())
        self.bridge.apply(dict(action='page',page='app_media'),None,Sink())
        self.assertFalse(self.bridge.state['routine']['running'])
    def test_seeded_random_repeats(self):
        def sequence():
            self.bridge.apply(dict(action='routine',name='random',seed=42),None,Sink())
            return [self.bridge.routine_actions() for _ in range(30)]
        self.assertEqual(sequence(),sequence())
    def test_threshold_entry_and_departure(self):
        self.bridge.apply(dict(action='routine',name='approach'),None,Sink())
        result=[self.bridge.routine_actions() for _ in range(14)]
        self.assertEqual(result[2][0]['payload']['label'],'300 m')
        self.assertEqual(result[-2][0]['payload']['label'],'0 m')
        self.assertEqual(result[-1][0]['payload']['label'],'301 m')
    def test_reject_malformed_inputs(self):
        actions=[dict(action='page',page='../firmware'),dict(action='input',event='reboot'),
            dict(action='data',topic='DRAW_ACK',payload={}),
            dict(action='data',topic='HUDIY_NAV',payload={'maneuver_type':4.5}),
            dict(action='data',topic='HUDIY_VALUES',payload={'values':['bad']}),
            dict(action='data',topic='HUDIY_PHONE',payload={'state':'FAKE'}),
            dict(action='can',can_id=0x800,data_hex='00'),dict(action='can',can_id=0x351,data_hex='zz'),
            dict(action='routine',name='random',seed=True),
            dict(action='config',icon_style='stock',high_resolution=True,approach_bar_max_distance=float('nan'))]
        for action in actions:
            with self.subTest(action=action),self.assertRaises(ValueError):server.validate(action)
    def test_offline_is_not_connected(self):
        self.assertFalse(self.bridge.snapshot()['connected'])
    def test_overflow_json_numbers(self):
        import json
        for raw in ('{"action":"data","topic":"HUDIY_NAV","payload":{"distance":1e999}}',
                    '{"action":"data","topic":"HUDIY_VALUES","payload":{"values":[{"id":"x","value":1e999}]}}'):
            with self.assertRaises(ValueError):server.validate(json.loads(raw))


if __name__=='__main__':unittest.main()
