"""Measured native/legacy layout and real BaseApp pixel scrolling regressions."""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dis_client'))
from font_metrics import measure_text, fit_text, font_profile
from apps.base import BaseApp
from icons import encode_audscii


class FontMetricsTests(unittest.TestCase):
    def test_all_measured_native_advances_match_browser_capture_and_legacy_x2(self):
        metrics=json.loads((ROOT/'dis_client/font_metrics_data.json').read_text())
        native_text=(ROOT/'dis_emulator/static/native_font_data.js').read_text()
        match=re.search(r'const data\s*=\s*',native_text)
        native,_=json.JSONDecoder().raw_decode(native_text[match.end():])
        legacy=(ROOT/'dis_emulator/static/font_data.js').read_text()
        for name, constant in (('fixed','FIXED'),('proportional','PROP'),('graphics','GRAPHICS')):
            entry=metrics['profiles']['native'][name]
            for glyph in native['fonts'][name]['glyphs']:
                actual=glyph['advance_px'];code=glyph['code']
                self.assertEqual(entry['advances_px'][code],12 if actual is None else actual)
                self.assertEqual(entry['width_status'][code],'fallback_max_cell' if actual is None else 'measured')
            match=re.search(r'const FONT_DATA_'+constant+r'\s*=\s*',legacy)
            table,_=json.JSONDecoder().raw_decode(legacy[match.end():])
            self.assertEqual(metrics['profiles']['legacy'][name]['advances_px'],[table[str(c)][0]*2 for c in range(256)])

    def test_narrow_and_wide_text_use_advance_not_character_count(self):
        self.assertEqual(measure_text('iii'),12)
        self.assertEqual(measure_text('WWW'),36)
        self.assertEqual(fit_text('iiiW',12),'iii')
        self.assertEqual(fit_text('WWW',12),'W')
        self.assertEqual(measure_text('100.0'),46)
        self.assertEqual(fit_text('100.0',44),'100.')
        self.assertEqual(measure_text('1',profile='legacy'),6)
        self.assertEqual(measure_text('1'),10)
        self.assertEqual(measure_text('i',flags=0x02),12)

    def test_encoder_unicode_and_conservative_unknown_are_shared(self):
        self.assertEqual(encode_audscii('¾¿↑😀'),bytes([0xBE,0xB9,0x18,0x20]))
        widths=json.loads((ROOT/'dis_client/font_metrics_data.json').read_text())['profiles']['native']['proportional']['advances_px']
        self.assertEqual(measure_text('¾¿↑😀'),sum(widths[c] for c in encode_audscii('¾¿↑😀')))
        self.assertEqual(measure_text('\0'),12)
        self.assertEqual(measure_text('\x1e'),12)
        self.assertEqual(measure_text(' '),4)
        self.assertEqual(fit_text('😀iii',8),'😀i')
        self.assertEqual(measure_text('Wi',flags=0x26),measure_text('Wi',flags=0x06))
        with self.assertRaises(ValueError):fit_text('A',-1)

    def test_config_profile_and_base_helpers(self):
        self.assertEqual(font_profile({}),'native')
        self.assertEqual(font_profile({'display':{'center_display': {'high_resolution': True}}}),'native')
        app=BaseApp({'display':{'center_display': {'high_resolution': False}}})
        self.assertEqual(app.text_width('111'),18)
        self.assertEqual(app.fit_text('1111',18),'111')

    def test_importer_retains_measured_width_when_bitmap_ambiguous(self):
        spec=importlib.util.spec_from_file_location('metrics_importer',ROOT/'tools/import_native_fonts.py')
        importer=importlib.util.module_from_spec(spec);spec.loader.exec_module(importer)
        native={'source_sha256':'synthetic','fonts':{'proportional':{'glyphs':[{'advance_px':None,'status':'missing'} for _ in range(256)]}}}
        native['fonts']['proportional']['glyphs'][0]={'advance_px':8,'status':'ambiguous'}
        with patch.object(importer,'build',return_value=native):
            data=importer.build_metrics('unused',ROOT/'dis_emulator/static/font_data.js')
        self.assertEqual(data['profiles']['native']['proportional']['advances_px'][:2],[8,12])
        self.assertEqual(data['profiles']['native']['fixed']['advances_px'],[12]*256)


class PixelScrollTests(unittest.TestCase):
    def setUp(self):
        self.app=BaseApp({})
        clock=patch('apps.base.time.monotonic');self.clock=clock.start();self.addCleanup(clock.stop)
        self.clock.return_value=0

    def window(self,text='WWiiii',**options):
        defaults={'max_width_px':12,'speed_ms':100,'start_pause_ms':0,'end_pause_ms':500,'continuous':False}
        defaults.update(options)
        return self.app._scroll_text(text,'title',**defaults)

    def test_width_windows_and_last_suffix_pause_then_restart(self):
        self.assertEqual(self.window(),'W')
        self.clock.return_value=.2;self.assertEqual(self.window(),'W')
        self.clock.return_value=.4;self.assertEqual(self.window(),'iii')
        self.clock.return_value=.6;self.assertEqual(self.window(),'iii')
        self.assertEqual(self.app._scroll_state['title']['offset'],3)
        self.clock.return_value=1.0;self.assertEqual(self.window(),'iii')
        self.clock.return_value=1.21;self.assertEqual(self.window(),'W')
        self.assertEqual(self.app._scroll_state['title']['offset'],0)

    def test_continuous_separator_and_wrap_always_fit(self):
        outputs=[]
        for step in range(15):
            self.clock.return_value=step*.2
            out=self.window('WiW',continuous=True)
            outputs.append(out)
            self.assertLessEqual(self.app.text_width(out),12)
        self.assertIn(chr(0x1F),outputs)
        self.assertEqual(outputs[0],'W')
        self.assertEqual(outputs[4],'W')

    def test_changed_text_width_flags_profile_and_mode_restart(self):
        self.window();self.clock.return_value=.2;self.window()
        self.assertEqual(self.app._scroll_state['title']['offset'],1)
        self.assertEqual(self.window('iiiWWW'),'iii')
        self.clock.return_value=.4;self.window('iiiWWW')
        self.assertEqual(self.window('iiiWWW',max_width_px=24),'iiiW')
        self.assertEqual(self.window('iiiWWW',font_flags=0x02),'i')
        self.app.config={'display':{'center_display': {'high_resolution': False}}}
        self.assertEqual(self.window('iiiWWW',font_flags=0x02),'i')
        self.assertEqual(self.app._scroll_state['title']['offset'],0)
        self.window('iiiWWW',continuous=True)
        self.assertEqual(self.app._scroll_state['title']['offset'],0)

    def test_fit_empty_clear_state_unchanged_keeps_phase_and_old_path(self):
        self.window();self.clock.return_value=.2;self.window()
        self.assertEqual(self.window(),'W')
        self.assertEqual(self.app._scroll_state['title']['offset'],1)
        self.assertEqual(self.window('iii'),'iii');self.assertNotIn('title',self.app._scroll_state)
        self.window();self.assertEqual(self.window(''),'');self.assertNotIn('title',self.app._scroll_state)
        self.assertEqual(self.app._scroll_text('WWW','old',max_len=2,start_pause_ms=0),'WW')
        self.clock.return_value=.4
        self.assertEqual(self.app._scroll_text('WWW','old',max_len=2,speed_ms=100,start_pause_ms=0),'WW')

    def test_start_pause_and_out_of_bounds_offset_recover(self):
        self.assertEqual(self.window(start_pause_ms=1000),'W')
        self.clock.return_value=.8;self.window(start_pause_ms=1000)
        self.assertEqual(self.app._scroll_state['title']['offset'],0)
        self.clock.return_value=1.1;self.window(start_pause_ms=1000)
        self.assertEqual(self.app._scroll_state['title']['offset'],1)
        self.app._scroll_state['title']['offset']=99
        self.assertEqual(self.window(start_pause_ms=1000),'W')


if __name__=='__main__':unittest.main()
