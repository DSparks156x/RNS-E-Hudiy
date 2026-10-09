import unittest
from _native_opening_peer import load,exercise,CAR,GEOMETRY

class NativeHandshakeControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load()
    def accepted(self,result,family=0x52):
        self.assertTrue(result['result'],result)
        self.assertIn(result['state'],('READY','PAUSED'))
        self.assertEqual(result['family'],family)
        self.assertEqual(result['setup_count'],1)
        self.assertEqual(result['commands'].count([1,1,0]),1)
        self.assertEqual(result['commands'].count([8]),1)
        self.assertEqual(result['capability_generation'],result['confirmed_generation'])
    def rejected(self,result):
        self.assertFalse(result['result'],result)
        self.assertEqual(result['state'],'DISCONNECTED')
        self.assertFalse(result['render_ready'])
        self.assertLess(result['elapsed'],30)
    def test_all_lengths_ignore_opaque_tail_and_need_no_geometry(self):
        for n in range(6,129):
            cap=[9,32,11]+[(i*31+n)&255 for i in range(n-3)]
            for ack in (False,True):
                with self.subTest(length=n,before_ack=ack):
                    r=exercise(self.m,cap,before_ack=ack)
                    self.accepted(r)
                    self.assertEqual(r['last_capabilities'],tuple(cap))
                    self.assertIsNone(r['geometry'])
    def test_native_formats_all_rx_sequence_and_ack_orders(self):
        for cap,family in ((CAR,0x52),([9,16,3,80,4,3],0x7A),([9,16,7,80,4,3],0x5A)):
            for seq in range(16):
                for ack in (False,True):
                    with self.subTest(family=family,sequence=seq,before_ack=ack):
                        self.accepted(exercise(self.m,cap,start_seq=seq,before_ack=ack),family)
    def test_all_format_and_company_values_select_only_native_families(self):
        for value in range(256):
            cap=[9,value,3,9,2,7]
            family=0x52 if value==32 else 0x7A if value==16 else None
            with self.subTest(format=value):self.accepted(exercise(self.m,cap),family)
            cap=[9,16,value,9,2,7]
            with self.subTest(company=value):self.accepted(exercise(self.m,cap),0x7A if value==3 else 0x5A)
    def test_car_compound_is_one_unsplit_opaque_record(self):
        cap=CAR+GEOMETRY
        for ack in (False,True):
            r=exercise(self.m,cap,before_ack=ack)
            self.accepted(r)
            self.assertEqual(r['last_capabilities'],tuple(cap))
            self.assertEqual(len(r['observations']),1)
    def test_unknown_first_format_control_setup_without_renderer(self):
        for ack in (False,True):
            r=exercise(self.m,[9,127,23,48,80,7],before_ack=ack)
            self.accepted(r,None)
            self.assertIsNotNone(r['setup_record'])
            self.assertFalse(r['render_ready'])
    def test_unknown_later_format_preserves_family_but_needs_new_setup(self):
        unknown=[9,127,23,48,80,7]
        def replies(count,command):
            return [unknown,[0x21,0x3B,command[2],0]] if count==1 else [[0x21,0x3B,command[2],0]]
        for ack in (False,True):
            r=exercise(self.m,setup_replies=replies,before_ack=ack)
            if r['result']:
                self.assertEqual(r['family'],0x52)
                self.assertGreaterEqual(r['setup_count'],2)
                self.assertEqual(r['capability_generation'],r['confirmed_generation'])
            else:self.rejected(r)
    def test_new_capabilities_during_setup_never_confirm_stale_request(self):
        def replies(count,command):
            return [[9,16,3,80,4,3],[0x21,0x3B,command[2],0]] if count==1 else [[0x21,0x3B,command[2],0]]
        for ack in (False,True):
            r=exercise(self.m,setup_replies=replies,before_ack=ack)
            if r['result']:
                self.assertEqual(r['family'],0x7A)
                self.assertGreaterEqual(r['setup_count'],2)
                self.assertEqual(r['capability_generation'],r['confirmed_generation'])
            else:self.rejected(r)
    def test_neverending_capabilities_fail_bounded_without_stale_ready(self):
        def replies(count,command):return [CAR,[0x21,0x3B,command[2],0]]
        for ack in (False,True): self.rejected(exercise(self.m,setup_replies=replies,before_ack=ack))
    def test_setup_priority_sentinel_and_variable_peer_byte(self):
        for record in ([0x21,0x17,0xA0,0],[0x21,0x99,255,255],[0x21,0x3B,0xA0,0,9,2]):
            for ack in (False,True):self.accepted(exercise(self.m,setup_replies=[[record]],before_ack=ack))
    def test_invalid_fresh_setup_retries_then_valid_confirmation(self):
        for invalid in ([0x21],[0x21,0x3B,0x10,0],[0x21,0x3B,0xA0]):
            for ack in (False,True):
                r=exercise(self.m,setup_replies=[[invalid],[[0x21,0x17,0xA0,0]]],before_ack=ack)
                self.assertTrue(r['result'],r)
                self.assertEqual(r['state'],'READY')
                self.assertEqual(r['setup_count'],2)
                self.assertEqual(r['capability_generation'],r['confirmed_generation'])
    def test_initial_release_ack_interruptions_do_not_publish_ready(self):
        for records in ((CAR,),([0x0B,3,0x20],),([0,2],),([0x14],),([0x53],)):
            for ack in (False,True):
                with self.subTest(records=records,before_ack=ack):
                    self.rejected(exercise(self.m,release_records=records,before_ack=ack))
        for control in ([0xA8],[0xA0,15,138,255,74,255]):
            for ack in (False,True):self.rejected(exercise(self.m,release_control=control,before_ack=ack))
    def test_malformed_mode_request_preserves_existing_setup_and_queues_native_error(self):
        for ack in (False,True):
            r=exercise(self.m,release_records=([0],),before_ack=ack)
            self.accepted(r)
            self.assertEqual(r['mode'],1)
            requests=list(r['instance']._deferred_application_requests)
            self.assertEqual(requests[-1]['reply'],(0x0B,3,0))
    def test_stale_missing_truncated_wrong_priority_setup_fails(self):
        for records,stale in (([],False),([],True),([[0x21]],False),([[0x21,0x3B,0x10,0]],False),([[0x21,0x3B,0xA0]],False)):
            for ack in ((True,) if stale else (False,True)):
                with self.subTest(records=records,stale=stale,before_ack=ack):self.rejected(exercise(self.m,setup_replies=[records],stale_setup=stale,before_ack=ack))
    def test_final_wait_interruptions_do_not_publish_ready(self):
        for records in (([0x0B,3,0x20],),([0x0B],),([0x53],),([0,2],),([0x14],),(CAR,)):
            with self.subTest(records=records):self.rejected(exercise(self.m,late=records))
    def test_setup_error_mode_restart_requests_fail(self):
        for record in ([0x0B,1,0x20],[0,2],[0x14]):
            for ack in (False,True):self.rejected(exercise(self.m,setup_replies=[[record,[0x21,0x3B,0xA0,0]]],before_ack=ack))
    def test_initial_status_does_not_block_valid_setup(self):
        for record,state in (([0x53,0x40],'PAUSED'),([0x53,0],'PAUSED'),([0x53,1],'READY'),([0x53,0x81],'READY')):
            for ack in (False,True):
                r=exercise(self.m,setup_replies=[[record,[0x21,0x3B,0xA0,0]]],before_ack=ack)
                self.accepted(r)
                self.assertEqual(r['state'],state)
    def test_initial_short_wrong_mode_capabilities_fail(self):
        for cap in ([9],[9,32,11,80,0],[9]+[32]*128):
            self.rejected(exercise(self.m,cap))
        self.rejected(exercise(self.m,CAR,mode_record=[0,2]))
    def test_optional_geometry_before_capabilities_short_red_compatibility(self):
        for mode in ('WHITE','RED'):
            for ack in (False,True):
                r=exercise(self.m,mode=mode,geometry=GEOMETRY,before_ack=ack)
                self.accepted(r)
                self.assertEqual(r['geometry'],GEOMETRY)
    def test_early_capabilities_during_mode_reply_need_no_duplicate_query(self):
        for ack in (False,True):
            r=exercise(self.m,capabilities_during_mode=True,before_ack=ack)
            self.assertTrue(r['result'],r)
            self.assertEqual(r['family'],0x52)
            self.assertGreaterEqual(r['setup_count'],1)
            # In the after-ACK case09 is not observed until later; one query
            #may already be submitted. Early observed09 must suppress it.
            if ack:self.assertEqual(r['query_count'],0)
    def test_optional_geometry_after_capabilities_ack_order_is_equivalent(self):
        for ack in (False,True):
            self.accepted(exercise(self.m,geometry=GEOMETRY,geometry_order='after',before_ack=ack))
    def test_session_close_and_reopen_never_publish_ready(self):
        for frame in ([0xA8],[0xA0,15,138,255,74,255]):
            for ack in (False,True):
                self.rejected(exercise(self.m,setup_control=frame,before_ack=ack))
            self.rejected(exercise(self.m,late_control=frame))
    def test_malformed_status_before_capabilities_never_recovers_to_ready(self):
        for ack in (False,True):
            self.rejected(exercise(self.m,query_prefix=([0x53],),before_ack=ack))
    def test_initial_mode_request_uses_native_length_guard(self):
        for ack in (False,True):
            self.accepted(exercise(self.m,mode_record=[0,1,99,42],before_ack=ack))
    def test_runtime_eligible_unknown_capabilities_keep_valid_family(self):
        for initial,family in ((CAR,0x52),([9,127,2,3,4,5],None)):
            r=exercise(self.m,initial)
            self.accepted(r,family)
            d=r['instance']
            seq=d._receive_seq_num
            d._retain_data([0x10|seq,9,127,2,3,4,5])
            self.assertTrue(d._application_setup_pending)
            self.assertFalse(d.renderer_ready())
            d.poll_bus_events()
            self.assertEqual(d.renderer_command_family(),family)
            self.assertFalse(d._application_setup_pending)
            self.assertIsNotNone(d.application_setup_record)
            self.assertEqual(d.state.name,'READY' if family else 'PAUSED')
    def test_capability_queue_overflow_never_publishes_ready(self):
        self.rejected(exercise(self.m,query_prefix=tuple(CAR for _ in range(33)),before_ack=True))
        r=exercise(self.m)
        self.accepted(r)
        d=r['instance']
        for _ in range(33):
            seq=d._receive_seq_num
            d._retain_data([0x10|seq]+CAR)
        self.assertIsNotNone(d._application_recovery_request)
        d.poll_bus_events()
        self.assertNotEqual(d.state.name,'READY')
        self.assertFalse(d.renderer_ready())
    def test_old_long_style_optional_setup_geometry_needs_no_repeated_commands(self):
        for mode in ('WHITE','RED'):
            for ack in (False,True):
                r=exercise(self.m,mode=mode,geometry=GEOMETRY,geometry_order='after',
                           setup_replies=[[GEOMETRY,[0x21,0x3B,0xA0,0]]],before_ack=ack)
                self.accepted(r)
                self.assertEqual(r['geometry'],GEOMETRY)
                self.assertEqual(r['commands'].count([0x33]),1)
    def test_geometry_inflight_reservation_bound_is_fail_closed(self):
        self.rejected(exercise(self.m,query_prefix=tuple(GEOMETRY for _ in range(5)),before_ack=True))
        # Four is an outstanding-record bound. Sequentially consumed geometry
        #does not overflow merely because its total count exceedsfour.
        self.accepted(exercise(self.m,query_prefix=tuple(GEOMETRY for _ in range(5)),before_ack=False))
    def test_early_mode_and_capability_during_announcement_ack(self):
        for ack in (False,True):
            r=exercise(self.m,announcement_capabilities=True,reply_to_query=False,before_ack=ack)
            self.assertTrue(r['result'],r)
            self.assertEqual(r['state'],'READY')
            self.assertEqual(r['family'],0x52)
            self.assertEqual(r['query_count'],0)
            self.assertEqual(r['setup_count'],1)
            self.assertEqual(len(r['observations']),1)
            self.assertEqual(r['commands'].count([1,1,0]),1)
    def test_new_geometry_at_release_and_final_keepalive_is_unknown_request(self):
        for ack in (False,True):
            for where in ('release','keepalive'):
                kwargs={'release_records':(GEOMETRY,)} if where=='release' else {'late':(GEOMETRY,)}
                r=exercise(self.m,before_ack=ack,**kwargs)
                self.accepted(r)
                self.assertIsNone(r['geometry'])
                requests=list(r['instance']._deferred_application_requests)
                self.assertEqual(requests[-1]['request'],tuple(GEOMETRY))
                self.assertEqual(requests[-1]['reply'],(0x0B,1,0x30))
    def test_post_confirmation_geometry_requires_already_received_reserved_object(self):
        replies=[[[0x21,0x3B,0xA0,0],GEOMETRY]]
        r=exercise(self.m,setup_replies=replies,before_ack=True)
        self.accepted(r)
        self.assertEqual(r['geometry'],GEOMETRY)
        self.assertFalse(r['instance']._deferred_application_requests)
        self.assertFalse(any(data[1:]==GEOMETRY for data in r['instance']._data_inbox))
        r=exercise(self.m,setup_replies=replies,before_ack=False)
        self.accepted(r)
        self.assertIsNone(r['geometry'])
        self.assertEqual(list(r['instance']._deferred_application_requests)[-1]['reply'],(0x0B,1,0x30))
    def test_prefetched_older_capability_does_not_overwrite_latest_typed_family(self):
        latest=[9,16,3,4,5,6]
        for ack in (False,True):
            r=exercise(self.m,latest,query_prefix=(CAR,),before_ack=ack)
            self.assertTrue(r['result'],r)
            self.assertEqual(r['state'],'READY')
            self.assertEqual(r['family'],0x7A)
            self.assertEqual(r['last_capabilities'],tuple(latest))
            self.assertEqual(r['capability_generation'],2)
            self.assertEqual(r['confirmed_generation'],2)
            self.assertEqual(r['setup_count'],2)
            self.assertTrue(r['instance'].renderer_ready(0x7A))
    def test_runtime_geometry_still_rejected_as_unknown_request(self):
        r=exercise(self.m)
        self.accepted(r)
        d=r['instance']
        seq=d._receive_seq_num
        d._retain_data([0x10|seq]+GEOMETRY)
        requests=list(d._deferred_application_requests)
        self.assertEqual(requests[-1]['reply'],(0x0B,1,0x30))

if __name__=='__main__':unittest.main(verbosity=2)
