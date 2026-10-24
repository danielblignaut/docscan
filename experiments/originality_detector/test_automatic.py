import unittest
from unittest.mock import patch
import numpy as np
from automatic import features, assess, GRID
from real_study import source_patch_features


class AutomaticTests(unittest.TestCase):
    def test_grid_needs_no_annotation(self):
        seen=[]
        def fake(rgb,centre):
            seen.append(centre)
            return np.full(51,len(seen),dtype=float)
        with patch('automatic.extract_patch',fake):
            values=features(np.zeros((600,800,3),np.uint8))
        self.assertEqual(len(seen),9)
        self.assertEqual(seen[0],[112.,112.])
        self.assertEqual(seen[-1],[688.,488.])
        np.testing.assert_array_equal(values,np.full(51,7.))

    def test_small_image_abstains(self):
        result=assess({'input_protocol':'rgb_grid_3x3_native224_q75','grid':GRID},np.zeros((223,300,3),np.uint8),allow_experimental=True)
        self.assertEqual(result['status'],'unknown')
        self.assertIsNone(result['confidence'])

    def test_author_xy_means_left_top(self):
        with patch('real_study.extract_patch',return_value=np.zeros(51)) as fn:
            source_patch_features(np.zeros((500,500,3),np.uint8),[0,10])
            np.testing.assert_array_equal(fn.call_args.args[1],[112.,122.])

if __name__=='__main__':unittest.main()
