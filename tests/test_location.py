import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import emulator_location_sim as gps


class LocationTests(unittest.TestCase):
    def test_random_walk_preserves_step_length_and_fixed_radius(self):
        center = (40.7357, -74.1724)
        rng = random.Random(42)
        # Exercise the center and multiple boundary starting positions.
        for start in (center, *(gps.destination(center, 999.99, angle)
                                for angle in (0, 1, 2, 3, 4, 5))):
            point = start
            for _ in range(10000):
                candidate = gps.next_position(rng, point, center)
                step = gps.distance_feet(point, candidate)
                self.assertGreaterEqual(step, 20 - 1e-6)
                self.assertLessEqual(step, 30 + 1e-6)
                self.assertLessEqual(gps.distance_feet(center, candidate), 1000)
                point = candidate

    def test_boundary_fallback_moves_inward_without_shortening_step(self):
        center = (40.7357, -74.1724)
        point = gps.destination(center, 1000, 0)
        class OutwardRandom:
            def uniform(self, low, high):
                return 25 if low == 20 else 0
        candidate = gps.next_position(OutwardRandom(), point, center)
        self.assertAlmostEqual(gps.distance_feet(point, candidate), 25, places=5)
        self.assertLess(gps.distance_feet(center, candidate), 1000)

    def test_controller_sends_longitude_first_and_stops_before_mutating_reused_serial(self):
        center = (40.7357, -74.1724)
        fixes = []
        identities = iter(['Test', 'Test', 'Other'])
        def adb_call(adb, *args):
            if args[-2:] == ('avd', 'name'):
                return next(identities) + '\nOK\n'
            fixes.append(args)
            return 'OK\n'
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gps, 'find_serial', return_value='emulator-5554'), \
                 patch.object(gps, 'adb_call', side_effect=adb_call), \
                 patch.object(gps.time, 'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                    gps.run_controller('adb', 'Test', Path(directory), center)
            self.assertEqual(len(fixes), 2)
            self.assertEqual(fixes[0], ('-s', 'emulator-5554', 'emu', 'geo', 'fix',
                                       '-74.1724', '40.7357', '0', '8'))
            for call in sleep.call_args_list:
                self.assertTrue(3 <= call.args[0] <= 5)
            state = json.loads((Path(directory) / 'location-state.json').read_text())
            self.assertEqual(state['tick'], 2)
            self.assertLessEqual(state['distance_feet'], 1000)
