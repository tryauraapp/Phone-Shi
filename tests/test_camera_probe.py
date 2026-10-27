import unittest

from camera_probe.build_and_run import motion_summary


class DirectFrameTests(unittest.TestCase):
    def samples(self, hashes):
        return [{'timestamp_ns': i * 1_000_000_000, 'sha256': value} for i, value in enumerate(hashes)]

    def test_frozen_source_is_not_verified(self):
        self.assertFalse(motion_summary(self.samples(['a'] * 22))['motion_verified'])

    def test_movie_that_moves_then_freezes_at_end_is_not_verified(self):
        self.assertFalse(motion_summary(self.samples(list('abcdefgh') + ['h'] * 14))['motion_verified'])

    def test_repeated_moving_sequence_across_both_halves_is_verified(self):
        result = motion_summary(self.samples(list('abcdefgh') * 3))
        self.assertTrue(result['motion_verified'])
        self.assertEqual(result['observed_span_seconds'], 23)

    def test_tiny_observation_window_is_not_a_pass(self):
        self.assertFalse(motion_summary(self.samples(list('abcd')))['motion_verified'])

    def test_no_frames_is_failure(self):
        self.assertFalse(motion_summary([])['motion_verified'])

    def test_preview_fps_uses_counter_deltas_over_the_observed_span(self):
        rows = self.samples(list('abcdef'))
        for index, row in enumerate(rows):
            row['consumer_updates'] = 120 + index * 30
        self.assertEqual(motion_summary(rows)['consumer_updates_per_second'], 30)

    def test_missing_preview_counters_do_not_claim_a_frame_rate(self):
        self.assertIsNone(motion_summary(self.samples(list('abcdef')))['consumer_updates_per_second'])
