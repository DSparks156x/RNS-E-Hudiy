"""Callback sequences observed in the two October 2026 Hudiy journals."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_hudiy_review_state import Handler, ManualTimer, Publisher


class CarPlayJournalTests(unittest.TestCase):
    def setUp(self):
        self.publisher = Publisher()
        self.capture = Mock()
        self.handler = Handler(self.publisher, event_capture=self.capture)
        self.addCleanup(self.handler.stop)

    def metadata(self, artist='', title='', album=''):
        message = SimpleNamespace(artist=artist, title=title, album=album,
                                  duration_label='', coverart=b'')
        self.handler.on_media_metadata(None, message)
        return message

    def media_status(self, source=2):
        self.handler.on_media_status(None, SimpleNamespace(
            source=source, is_playing=False, position_label='0:00'))

    def cover_events(self):
        return [data for topic, data in self.publisher.events if topic == b'HUDIY_COVERART']

    def raw_metadata_calls(self):
        return [call for call in self.capture.record.call_args_list
                if call.args[0] == 'media_metadata']

    def test_both_journals_idle_dash_snapshot_is_not_a_track(self):
        message = self.metadata('-', '-', '-')
        self.metadata('-', '-', '-')  # Same snapshot is resent on subscription refresh.
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], '')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['artist'], '')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['album'], '')
        self.assertEqual(self.cover_events(), [])
        self.assertIsNone(self.handler.last_media)
        raw = self.raw_metadata_calls()
        self.assertEqual(len(raw), 2)
        self.assertIs(raw[0].args[1], message)
        self.assertEqual(message.title, '-')

    def test_legitimate_dash_title_with_artist_survives_even_before_source_status(self):
        self.metadata('Artist', '-', 'Album')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], '-')
        self.assertEqual(len(self.cover_events()), 1)

    def test_known_source_dash_title_is_not_the_idle_placeholder(self):
        self.media_status()
        self.metadata('-', '-', '-')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], '-')

    @patch('threading.Timer', ManualTimer)
    def test_journal_one_initial_album_artist_title_burst_has_one_track_clear(self):
        self.metadata('-', '-', '-')
        self.media_status()
        count = len(self.publisher.events)
        album_only = self.metadata(album='IIII')
        pending = self.handler._pending_media_clear
        self.assertEqual(pending.interval, 0.25)
        self.assertEqual(len(self.publisher.events), count)
        artist = 'VIER, Machinedrum, Holly, Thys, Salvador Breed'
        artist_album = self.metadata(artist=artist, album='IIII')
        self.assertIs(self.handler._pending_media_clear, pending)
        self.assertEqual(len(self.publisher.events), count)
        complete = self.metadata(artist=artist, title='THE SOURCE', album='IIII')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'THE SOURCE')
        self.assertEqual(len(self.cover_events()), 1)
        self.assertTrue(pending.cancelled)
        pending.fire()
        self.assertEqual(len(self.cover_events()), 1)
        self.assertEqual([call.args[1] for call in self.raw_metadata_calls()][-3:],
                         [album_only, artist_album, complete])

    @patch('threading.Timer', ManualTimer)
    def test_untitled_burst_preserves_established_track_and_cover_until_title(self):
        self.media_status()
        self.metadata('Previous Artist', 'Previous Track', 'Previous Album')
        self.handler.last_coverart_hash = 'previous-cover'
        count = len(self.publisher.events)
        self.metadata(album='Next Album')
        self.metadata(artist='Next Artist', album='Next Album')
        self.assertEqual(len(self.publisher.events), count)
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Previous Track')
        self.assertEqual(self.handler.last_coverart_hash, 'previous-cover')
        self.metadata('Next Artist', 'Next Track', 'Next Album')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Next Track')
        self.assertEqual(len(self.cover_events()), 2)

    @patch('threading.Timer', ManualTimer)
    def test_partial_deadline_applies_latest_snapshot_without_extending(self):
        self.media_status()
        self.metadata(album='IIII')
        pending = self.handler._pending_media_clear
        self.metadata(artist='VIER', album='IIII')
        self.assertIs(self.handler._pending_media_clear, pending)
        pending.fire()
        media = self.publisher.latest(b'HUDIY_MEDIA')
        self.assertEqual((media['artist'], media['title'], media['album']), ('VIER', '', 'IIII'))
        self.assertIsNone(self.handler._pending_media_clear)
        self.assertEqual(len(self.raw_metadata_calls()), 2, 'Timer application must not duplicate raw callbacks')

    @patch('threading.Timer', ManualTimer)
    def test_complete_track_updates_are_immediate_with_no_timer(self):
        self.media_status()
        self.metadata('Artist', 'First', 'Album')
        self.metadata('Artist', 'Second', 'Album')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Second')
        self.assertIsNone(self.handler._pending_media_clear)

    @patch('threading.Timer', ManualTimer)
    def test_partial_timer_is_canceled_by_source_switch_and_shutdown(self):
        for cancel in (lambda: self.media_status(source=3), self.handler.stop):
            with self.subTest(cancel=cancel):
                self.media_status()
                self.metadata(album='IIII')
                pending = self.handler._pending_media_clear
                cancel()
                count = len(self.publisher.events)
                pending.fire()
                self.assertTrue(pending.cancelled)
                self.assertIsNone(self.handler._pending_media_metadata)
                self.assertEqual(len(self.publisher.events), count)

    def test_journal_two_complete_metadata_before_source_status_is_preserved(self):
        # Journal 2 receives this metadata 407 ms before CarPlay's source status.
        self.metadata('RSK XFM', 'S03E05 | Remastered', 'RSK XFM')
        initial = self.publisher.latest(b'HUDIY_MEDIA')
        self.assertEqual(initial['title'], 'S03E05 | Remastered')
        self.assertEqual(initial['source_id'], 0)
        for _ in range(3):  # Full metadata repeats before SOURCE CHANGED.
            self.metadata('RSK XFM', 'S03E05 | Remastered', 'RSK XFM')
        self.media_status()
        media = self.publisher.latest(b'HUDIY_MEDIA')
        self.assertEqual((media['artist'], media['title'], media['album']),
                         ('RSK XFM', 'S03E05 | Remastered', 'RSK XFM'))
        self.assertEqual(media['media_state'], 'PAUSED')
        self.assertEqual(len(self.cover_events()), 1)

    def test_projection_inactive_is_visibility_and_does_not_clear_valid_route(self):
        self.handler.on_navigation_status(None, SimpleNamespace(source=2, state=1))
        self.handler.on_navigation_maneuver_details(None, SimpleNamespace(
            description='Main St', maneuver_type=4, maneuver_side=2,
            maneuver_angle=0, icon=b''))
        self.handler.on_projection_status(None, SimpleNamespace(active=False))
        self.assertTrue(self.handler.nav_active)
        self.assertEqual(self.handler.current_nav_data['description'], 'Main St')


if __name__ == '__main__':
    unittest.main()
