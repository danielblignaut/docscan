"""No corpus reads: test safeguards using procedural inputs only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import run

class ProtocolTests(unittest.TestCase):
    def test_pins_reject_wrong_split_or_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'value';p.write_bytes(b'procedural')
            manifest={'split':'dev','files':[{'path':'value','size':p.stat().st_size,'sha256':run.sha(p)}]}
            run.verify(root,manifest)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):run.verify(root,manifest)
            with self.assertRaises(ValueError):run.verify(root,{'split':'test','files':[]})

    def test_no_quad_is_identity_fallback(self):
        config=json.loads((run.HERE/'candidates.json').read_text())
        image=np.full((400,600,3),127,np.uint8)
        out,info=run.quad_transform(image,config['auto_quad'])
        self.assertFalse(info['found']);self.assertIs(out,image)

    def test_quad_has_distinct_corners_and_landscape_output(self):
        config=json.loads((run.HERE/'candidates.json').read_text())
        image=np.zeros((600,800,3),np.uint8)
        points=np.array([[90,120],[690,70],[730,450],[60,500]],np.int32)
        cv2.fillConvexPoly(image,points,(235,235,235))
        out,info=run.quad_transform(image,config['auto_quad'])
        self.assertTrue(info['found']);self.assertEqual(len(set(map(tuple,info['corners']))),4)
        self.assertGreater(out.shape[1],out.shape[0])

    def test_timeout_is_not_success(self):
        config=json.loads((run.HERE/'candidates.json').read_text())
        with patch('run.subprocess.run',side_effect=run.subprocess.TimeoutExpired('scan',180)):
            output,_=run.native(Path('/procedural/image'),config)
        self.assertTrue(output['timeout']);self.assertFalse(output.get('accepted',False))

    def test_existing_trial_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'frozen-id.json').write_text('{}')
            with patch('run.WORK',root):
                with self.assertRaises(FileExistsError):run.frozen_provenance({},'id')

if __name__=='__main__':unittest.main()
