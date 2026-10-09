"""Legacy atomic packet capacity, full scroll reach and phone highlights."""
import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dis_client'))
from apps.base import BaseApp
from apps.media import MediaApp
from apps.phone import PhoneApp
from font_metrics import measure_text,text_character_capacity
from text_render import text_update,text_bounds
import test_measured_text_updates as atomicfixtures
import test_media_pixel_width as mediafixtures

LEGACY={'display':{'center_display': {'high_resolution': False},'text_centering':True}}


class AtomicTextCapacityTests(unittest.TestCase):
    def test_reserves_clear_and_inverted_windows(self):
        for config in (LEGACY,dict(LEGACY,ddp_bitmap_message_bytes=42)):
            self.assertEqual(text_character_capacity(6,'legacy',config),23)
            self.assertEqual(text_character_capacity(0x86,'legacy',config),9)
        self.assertEqual(text_character_capacity(6,'native',{}),86)
        self.assertEqual(text_character_capacity(6,'native',{'ddp_bitmap_message_bytes':42}),86)

    def test_thin_legacy_string_scrolls_to_tail_even_when_pixel_width_fits(self):
        text='i'*27+'l'
        app=BaseApp(LEGACY)
        self.assertLessEqual(measure_text(text,profile='legacy'),128)
        outputs=[]
        with patch('apps.base.time.monotonic') as clock:
            for tick in range(7):
                clock.return_value=tick*.2
                outputs.append(app._scroll_text(text,'thin',max_width_px=128,
                    speed_ms=100,start_pause_ms=0,end_pause_ms=1000,continuous=False))
        self.assertTrue(all(len(window)<=23 for window in outputs))
        self.assertTrue(any(window.endswith('l') for window in outputs))
        self.assertEqual(app._scroll_state['thin']['offset'],len(text)-23)

    def test_legacy_byte_overflow_is_left_aligned_and_native32i_is_unchanged(self):
        app=MediaApp(LEGACY)
        app.title='i'*27+'l'
        text,flags=app.get_view()['line1']
        self.assertEqual(flags,6)
        self.assertEqual(len(text),23)
        native=MediaApp({'display':{'center_display': {'high_resolution': True},'text_centering':True}})
        native.title='i'*32
        self.assertEqual(native.get_view()['line1'],('i'*32,0x26))
        self.assertNotIn('media_title',native._scroll_state)

    def test_phone_caller_width_and_legacy_capacity_both_scroll_to_tail(self):
        for profile,text in [('native','W'*14+'Z'),('legacy','i'*27+'l')]:
            with self.subTest(profile=profile):
                cfg={'display':{'center_display': {'high_resolution': profile == 'native'},
                    'text_scrolling':{'speed_ms':100,'start_delay_ms':0,'end_delay_ms':1000}}}
                phone=PhoneApp(cfg)
                phone.state='ACTIVE'
                phone.caller_name=text
                seen=[]
                with patch('apps.base.time.monotonic') as clock:
                    for tick in range(20):
                        clock.return_value=tick*.2
                        window=phone.get_view()['line2'][0]
                        seen.append(window)
                        self.assertLessEqual(measure_text(window,profile=profile),128)
                        self.assertLessEqual(len(window),text_character_capacity(6,profile,cfg))
                self.assertTrue(any(window.endswith(text[-1]) for window in seen))

    def test_old_new_footprints_are_measured_after_same_capacity_fit(self):
        old=dict(text='i'*32,x=0,y=8,flags=6)
        new=dict(text='i',x=0,y=8,flags=6)
        update=text_update(new,old,profile='legacy',config=LEGACY)
        self.assertEqual(update['clear_rect']['w'],text_bounds(dict(old,text='i'*23),'legacy')[2])

    def test_dictionary_history_stores_sent_legacy_text(self):
        fixture=mediafixtures.DictionaryTextLines()
        fixture.setUp()
        fixture.e.cfg=LEGACY
        fixture.e.current_app.get_view.return_value={'line1':('i'*32,6)}
        fixture.e._draw()
        self.assertEqual(fixture.e.last_sent['line1'],'i'*23)
        self.assertEqual(fixture.commands()[0]['text'],'i'*23)

    def test_legacy_phone_labels_fit_atomic_highlight_clear_and_replacement(self):
        fixture=atomicfixtures.AtomicServiceTextTests()
        fixture.setUp()
        fixture.s.ddp.dis_mode='red'
        phone=PhoneApp(LEGACY)
        phone.set_control_mode(True)
        for state,index,line,label in [('INCOMING',0,'line4','>Accept'),
                                        ('INCOMING',1,'line5','>Reject'),
                                        ('ACTIVE',0,'line5','End Call')]:
            phone.state,phone.action_idx=state,index
            text,flags=phone.get_view()[line]
            self.assertEqual(text,label)
            self.assertTrue(flags&0x80)
            y=31 if line=='line4' else 41
            update=text_update(dict(text=text,x=0,y=y,flags=flags),
                dict(text='Previous',x=0,y=y,flags=6),profile='legacy',
                viewport=(0,y,64,min(9,48-y)),config=LEGACY)
            self.assertIn('clear_rect',update)
            self.assertLessEqual(len(fixture.s.get_text_update_payload(update)),42)

    def test_custom_fields_fit_both_replacement_and_previous_history(self):
        tree=ast.parse((ROOT/'dis_client/dis_display.py').read_text())
        ns={}
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_prepare_text_group')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'dis_display.py','exec'),ns)
        engine=type('Engine',(),{'_prepare_text_group':ns['_prepare_text_group']})()
        engine.cfg=LEGACY
        old=[dict(cmd='draw_text',text='i'*32,x=0,y=39,flags=6)]
        new=[dict(cmd='clear_area',x=0,y=39,w=61,h=9),
             dict(cmd='draw_text',text='i',x=0,y=39,flags=6)]
        prepared=engine._prepare_text_group(new,old,'legacy','street')
        self.assertEqual(len(prepared),1)
        self.assertEqual(prepared[0]['clear_rect']['w'],text_bounds(dict(old[0],text='i'*23),'legacy')[2])


if __name__=='__main__':unittest.main()
