"""Mode events are real native00 requests, never ignored fork bytes."""
import unittest
from _native_opening_peer import load,exercise,CAR

class OpeningModeEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.m=load(name='mode_event_controller_under_test')
    def confirmed(self,r,family=0x52,state='READY'):
        self.assertTrue(r['result'],r)
        self.assertEqual(r['state'],state)
        self.assertEqual(r['mode'],1)
        self.assertEqual(r['family'],family)
        self.assertEqual(r['capability_generation'],r['confirmed_generation'])
        self.assertIsNotNone(r['setup_record'])
        self.assertFalse(any(frame==[0xA8] for frame in r['tx']))
        frames=[frame for frame in r['tx'] if frame[0]>>4 in (0,1,2,3)]
        self.assertEqual([frame[0]&15 for frame in frames],[i&15 for i in range(len(frames))])
    def test_repeated_mode1_during_announcement_reply_configuration_or_query(self):
        for phase in (0x15,1,8):
            for mode_record in ([0,1],[0,1,11,22,33]):
                for ack in (False,True):
                    def script(command,occurrence):
                        if command[0]==phase and occurrence==1:
                            if phase==0x15:return [[0,1],mode_record]
                            return [mode_record]
                        return None
                    with self.subTest(phase=phase,record=mode_record,before_ack=ack):
                        r=exercise(self.m,before_ack=ack,command_script=script)
                        self.confirmed(r)
                        self.assertGreaterEqual(r['commands'].count([1,1,0]),2)
                        self.assertGreaterEqual(r['query_count'],1)
    def test_two_mode_events_then_capabilities_queue_two_replies_and_one_setup(self):
        for ack in (False,True):
            def script(command,occurrence):
                if command[0]==0x15:return [[0,1],[0,1],CAR]
                if command==[8]:return []
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.confirmed(r)
            self.assertEqual(r['commands'].count([1,1,0]),2)
            self.assertEqual(r['query_count'],0)
            self.assertEqual(r['setup_count'],1)
    def test_discovery_mode_events_do_not_require_a_known52_family(self):
        for cap,family,state in (([9,127,23,4,5,6],None,'PAUSED'),([9,16,3,4,5,6],0x7A,'READY')):
            for ack in (False,True):
                def script(command,occurrence):
                    if command==[8] and occurrence==1:return [[0,1]]
                    return None
                r=exercise(self.m,cap,before_ack=ack,command_script=script)
                self.confirmed(r,family,state)
    def test_repeated_mode1_with_capabilities_on_reply_instead_of_query(self):
        for ack in (False,True):
            def script(command,occurrence):
                if command==[1,1,0]:return [[0,1]] if occurrence==1 else [CAR]
                if command==[8]:return []
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.confirmed(r)
            self.assertGreaterEqual(r['commands'].count([1,1,0]),2)
    def test_mode1_after_capability_invalidates_old_generation_and_requires_query(self):
        # Both09and00must be actually received beforethefirst20 submission.
        for ack in (True,):
            def script(command,occurrence):
                if command==[8] and occurrence==1:return [CAR,[0,1]]
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.confirmed(r)
            self.assertGreaterEqual(r['commands'].count([1,1,0]),2)
            self.assertGreaterEqual(r['query_count'],2)
            self.assertGreaterEqual(r['capability_generation'],2)
    def test_discovery_mode_event_retains_last_valid_family_for_unknown_refresh(self):
        unknown=[9,127,23,4,5,6]
        def script(command,occurrence):
            if command==[8]:return [CAR,[0,1]] if occurrence==1 else [unknown]
            return None
        r=exercise(self.m,before_ack=True,command_script=script)
        self.confirmed(r)
        self.assertGreaterEqual(r['query_count'],2)
        self.assertEqual(r['last_capabilities'],tuple(unknown))
        self.assertGreaterEqual(r['capability_generation'],2)
    def test_mode_event_received_during_reply_ack_retires_unsent_older_setup(self):
        for ack in (True,):
            def script(command,occurrence):
                if command[0]==0x15:return [[0,1],CAR]
                if command==[1,1,0] and occurrence==1:return [[0,1]]
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.confirmed(r)
            self.assertEqual(r['commands'].count([1,1,0]),2)
            self.assertEqual(r['query_count'],1)
            self.assertEqual(r['setup_count'],1)
            self.assertEqual(r['capability_generation'],2)
    def test_mode1_during_setup_is_explicitly_unsupported_and_fails_closed(self):
        for ack in (False,True):
            def script(command,occurrence):
                if command[0]==0x20 and occurrence==1:return [[0,1],[0x21,0x3B,0xA0,0]]
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.assertFalse(r['result'],r)
            self.assertEqual(r['state'],'DISCONNECTED')
            self.assertFalse(r['render_ready'])
    def test_unreceived_queued_mode1_first_seen_during20_fails_closed(self):
        def script(command,occurrence):
            if command==[8] and occurrence==1:return [CAR,[0,1]]
            return None
        r=exercise(self.m,before_ack=False,command_script=script)
        self.assertFalse(r['result'],r)
        self.assertEqual(r['state'],'DISCONNECTED')
        self.assertFalse(r['render_ready'])
    def test_mode2_after_capabilities_or_during_setup_remains_fail_closed(self):
        for phase in (8,0x20):
            for ack in (False,True):
                def script(command,occurrence):
                    if command[0]==phase and occurrence==1:
                        return [CAR,[0,2]] if phase==8 else [[0,2],[0x21,0x3B,0xA0,0]]
                    return None
                r=exercise(self.m,before_ack=ack,command_script=script)
                self.assertFalse(r['result'],r)
                self.assertEqual(r['state'],'DISCONNECTED')
                self.assertFalse(r['render_ready'])
    def test_repeated_mode1_events_without_progress_fail_bounded(self):
        for ack in (False,True):
            def script(command,occurrence):
                if command==[1,1,0]:return [[0,1]]
                if command==[8]:return []
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.assertFalse(r['result'],r)
            self.assertEqual(r['state'],'DISCONNECTED')
            self.assertFalse(r['render_ready'])
            self.assertLessEqual(r['commands'].count([1,1,0]),33)
    def test_repeated_mode1_missing_new_capabilities_never_returns_ready(self):
        for ack in (False,True):
            def script(command,occurrence):
                if command==[8]:return [CAR,[0,1]] if occurrence==1 else []
                return None
            r=exercise(self.m,before_ack=ack,command_script=script)
            self.assertFalse(r['result'],r)
            self.assertEqual(r['state'],'DISCONNECTED')
            self.assertFalse(r['render_ready'])
            self.assertLess(r['elapsed'],30)

if __name__=='__main__':unittest.main(verbosity=2)
