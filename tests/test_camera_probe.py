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
