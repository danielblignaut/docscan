import unittest
import tempfile
from pathlib import Path
from run import starts, ios, ref, artifact_state

class GeometryTests(unittest.TestCase):
    def test_artifact_guards_do_not_collapse_same_named_models(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/role/'inference.onnx' for role in ['det','rec']]
            for p in paths:
                p.parent.mkdir();p.write_bytes(b'original')
            before=artifact_state(paths)
            self.assertEqual(len(before),2)
            paths[0].write_bytes(b'changed detector')
            self.assertNotEqual(artifact_state(paths),before)

    def test_last_slice_covers_page_end(self):
        points=starts(1650,640,160)
        self.assertEqual(points,[0,480,960,1010])
        self.assertEqual(points[-1]+640,1650)
        self.assertEqual(starts(500,640,160),[0])

    def test_duplicate_line_suppression_does_not_merge_adjacent_rows(self):
        def box(x,y,w,h):return ref.np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],dtype=ref.np.float32)
        self.assertGreater(ios(box(0,0,100,10),box(1,1,98,8)),.7)
        self.assertEqual(ios(box(0,0,100,10),box(0,12,100,10)),0.)

if __name__=='__main__':unittest.main()
