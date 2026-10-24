import copy
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from active_replay import summarize, write_clip


def trial():
    return {'result': {'passed': False, 'completed': False, 'frames': 1,
                       'checks': [{'name': k, 'required': True, 'passed': False, 'threshold': 1.}
                                  for k in ('coverage', '3d_motion', 'antispoof', 'continuity', 'identity')]},
            'trace': [{'phase': 'centre', 'hint': 'Move closer'}], 'antispoof': [], 'parallax': []}


class ActiveTests(unittest.TestCase):
    def test_incomplete_attack_is_not_evidence_of_measured_pad(self):
        result = summarize([trial()])
        self.assertEqual(result['attacks_accepted'], 0)
        self.assertEqual(result['entered_sweep'], 0)
        self.assertEqual(result['clips_with_passive_samples'], 0)
        self.assertEqual(result['clips_with_parallax_samples'], 0)
        self.assertIsNone(result['bpcer'])
        self.assertEqual(result['final_phases'], {'centre': 1})

    def test_disabled_physical_check_aborts_evaluation(self):
        run = trial()
        run['result']['checks'][1]['required'] = False
        with self.assertRaises(ValueError):
            summarize([run])

    def test_invalid_decision_or_truncated_trace_aborts(self):
        run = trial()
        run['result']['passed'] = True
        with self.assertRaises(ValueError):
            summarize([run])
        run = trial()
        run['trace'] = []
        with self.assertRaises(ValueError):
            summarize([run])

    def test_accepted_attack_counts_even_when_others_fail(self):
        good = trial()
        good['result'].update(passed=True, completed=True)
        for check in good['result']['checks']:
            check['passed'] = True
        good['trace'][0]['phase'] = 'done'
        good['antispoof'] = [0.9]
        good['parallax'] = [[0.1, 0.5]]
        result = summarize([trial(), good])
        self.assertEqual(result['observed_attack_acceptance_rate'], .5)
        self.assertEqual(result['completed_sessions'], 1)
        changed = copy.deepcopy(good)
        changed['result']['checks'][1]['threshold'] = .5
        with self.assertRaises(ValueError):
            summarize([good, changed])

    def test_sampling_preserves_full_clip_duration_and_y4m_shape(self):
        # Procedural colour frames only; no biometric fixture.
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder) / 'synthetic.avi', Path(folder) / 'clip.y4m'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 30., (64, 48))
            self.assertTrue(writer.isOpened())
            for i in range(12):
                writer.write(np.full((48, 64, 3), i * 10, dtype=np.uint8))
            writer.release()
            metadata = write_clip(source, out)
            self.assertEqual(metadata['source_frames'], 12)
            self.assertEqual(metadata['sampled_frames'], 4)
            self.assertEqual(metadata['sample_fps'], 10.)
            header, payload = out.read_bytes().split(b'\n', 1)
            self.assertIn(b'W64 H48 F10:1', header)
            self.assertEqual(len(payload), 4 * (6 + 64 * 48 * 3 // 2))


if __name__ == '__main__':
    unittest.main()
