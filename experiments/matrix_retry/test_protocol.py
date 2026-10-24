"""Dataset-free harness regressions; native geometry regressions live in barcode.rs."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import run


class ProtocolTests(unittest.TestCase):
    def test_entire_candidate_has_one_timeout_budget(self):
        with patch('run.subprocess.run', side_effect=subprocess.TimeoutExpired('probe',30)) as call:
            output = run.invoke('matrix_both','unused.png')
        self.assertTrue(output['timeout'])
        self.assertEqual(output['barcodes'],[])
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.kwargs['timeout'],30)
        self.assertEqual(Path(call.call_args.args[0][0]).name,'after')

    def test_decode_includes_payload_bytes_and_points_without_rewriting(self):
        code = {'format':'qrcode','text':'synthetic','bytes':[0,255,17],'points':[[12.5,34.25]]}
        with patch('run.subprocess.run', return_value=subprocess.CompletedProcess([],0,json.dumps({'barcodes':[code],'ms':1.25}),'')):
            output = run.invoke('empty_half','unused.png',7)
        self.assertEqual(output['barcodes'],[code])
        self.assertEqual(output['ms'],1.25)

    def test_crash_is_not_silently_a_successful_empty_frame(self):
        with patch('run.subprocess.run', return_value=subprocess.CompletedProcess([],101,'','panic')):
            output = run.invoke('empty_half','unused.png')
        self.assertTrue(output['crash'])
        self.assertFalse(output['timeout'])
        self.assertEqual(output['barcodes'],[])

    def test_paired_deltas_decode_compact_scorer_bits(self):
        a = {'ids':['a','b','c'], 'ok':'010'}
        b = {'ids':['a','b','c'], 'ok':'101'}
        self.assertEqual(run.changed_ids(a,b), {'new_true_ids':[run.opaque('a'),run.opaque('c')], 'lost_true_ids':[run.opaque('b')]})

    def test_only_full_dev_is_declared(self):
        config = json.loads((Path(__file__).parent/'protocol.json').read_text())
        self.assertEqual(config['datasets'],{'barcode_public_dev':277,'barcode_synth_dev':300})
        self.assertEqual(config['split'],'dev')
        self.assertEqual(config['latency']['repeats'],4)
        self.assertEqual(config['timeout_seconds'],30)
        self.assertEqual(set(config['variants']),set(run.MODES))


if __name__=='__main__':
    unittest.main()
