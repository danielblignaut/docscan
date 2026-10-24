"""Synthetic correspondence, numerical and no-detection regressions only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import matching_photometric as m


def rows(pose='neutral', ids=('a','b','c'), split='validation'):
    return [dict(id=i, split=split, pose=pose, condition='original') for i in ids]


class MatchingTests(unittest.TestCase):
    def test_reference_permutation_preserves_identity_labels_and_metrics(self):
        p, r = rows(), rows('smile', ('c','a','b'))
        vectors = np.eye(3, dtype=np.float32)
        s, y = m.pair_scores(p, vectors, np.ones(3,bool), r, vectors[[2,0,1]], np.ones(3,bool))
        self.assertFalse(np.array_equal(y,np.eye(3,dtype=bool)))
        self.assertEqual(m.referee.rates(s,y,.356)['genuine_accepted'],3)
        self.assertEqual(m.referee.rates(s,y,.356)['impostors_accepted'],0)

    def test_gamma_correspondence_joins_by_key_not_position(self):
        original = rows()
        vectors = np.diag([2.,3.,4.]).astype(np.float32)
        shuffled = [original[i] for i in (2,0,1)]
        views = [(original,vectors,np.ones(3,bool)),(shuffled,vectors[[2,0,1]],np.ones(3,bool)),(original,vectors,np.ones(3,bool))]
        v,f = m.aggregate_views(original,views)
        np.testing.assert_allclose(v,np.eye(3))
        self.assertTrue(f.all())
        with self.assertRaisesRegex(ValueError,'correspondence'):
            m.corresponding_rows(original,rows(ids=('a','b','wrong')))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            m.corresponding_rows(original,rows(ids=('a','b','b')))

    def test_unit_normalization_before_and_after_equal_mean(self):
        r = rows(ids=('a',))
        views = [(r,np.array([v],np.float32),np.array([True])) for v in ([100,0],[0,2],[0,3])]
        v,f = m.aggregate_views(r,views)
        np.testing.assert_allclose(v,[[1/np.sqrt(5),2/np.sqrt(5)]],rtol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(v,axis=1),1)
        self.assertTrue(f.all())

    def test_missing_view_rejects_without_denominator_loss(self):
        r=rows()
        vectors=np.eye(3,dtype=np.float32)
        views=[(r,vectors,np.array([True,True,True])),(r,vectors,np.array([False,True,True])),(r,vectors,np.array([True,True,True]))]
        v,f=m.aggregate_views(r,views)
        self.assertFalse(f[0])
        np.testing.assert_array_equal(v[0],0)
        score,label=m.pair_scores(r,v,f,rows('smile'),vectors,np.array([True,False,True]))
        self.assertEqual(int(label.sum()),3)
        self.assertEqual(int((~label).sum()),6)
        self.assertTrue(np.isneginf(score[0]).all())
        self.assertTrue(np.isneginf(score[:,1]).all())
        rates=m.referee.rates(score,label,.356)
        self.assertEqual(rates['genuine_accepted'],1)
        self.assertEqual(rates['tar'],1/3)
        score[:]=-np.inf
        self.assertEqual(m.referee.rates(score,label,-1)['genuine_accepted'],0)

    def test_nonfinite_zero_overflow_and_cancelling_vectors_reject(self):
        v,f=m.normalized([[np.nan,0],[np.inf,0],[0,0],[1e38,1e38],[3,4]],np.ones(5,bool))
        np.testing.assert_array_equal(f,[False,False,False,False,True])
        self.assertTrue(np.isfinite(v).all())
        np.testing.assert_allclose(v[-1],[.6,.8])
        r=rows(ids=('a',))
        views=[(r,np.array([v],np.float32),np.array([True])) for v in ([1,0],[-.5,np.sqrt(.75)],[-.5,-np.sqrt(.75)])]
        v,f=m.aggregate_views(r,views)
        self.assertFalse(f.any())

    def test_duplicate_incomplete_cross_split_pairs_abort(self):
        v=np.eye(3,dtype=np.float32); f=np.ones(3,bool)
        for ref in (rows('smile',ids=('a','a','c')),rows('smile',ids=('a','b','wrong')),rows('smile',split='calibration')):
            with self.assertRaises(ValueError):
                m.pair_scores(rows(),v,f,ref,v,f)

    def test_native_missing_first_and_all_missing_keep_row_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.f32'
            for found in ([False,True,True],[False,False,False]):
                np.eye(3,dtype='<f4').tofile(path)
                Path(str(path)+'.json').write_text(json.dumps(dict(dim=3,items=[dict(found=x,presence=1.) for x in found])))
                v,f=m.read_native(path,3)
                np.testing.assert_array_equal(f,found)
                self.assertEqual(v.shape,(3,3))
                np.testing.assert_array_equal(v[~f],0)
            # Non-finite/low mesh presence rejects a found detection.
            Path(str(path)+'.json').write_text(json.dumps(dict(dim=3,items=[dict(found=True,presence=x) for x in (float('inf'),.49,1.)])))
            v,f=m.read_native(path,3)
            np.testing.assert_array_equal(f,[False,False,True])
            with self.assertRaises(ValueError):
                m.read_native(path,2)

    def test_gamma_unit_identity_fixed_transform_and_no_range_overflow(self):
        pixels=np.arange(256,dtype=np.uint8).reshape(16,16)
        image=Image.fromarray(pixels).convert('RGB')
        np.testing.assert_array_equal(np.asarray(m.gamma_image(image,1)),np.asarray(image))
        bright=np.asarray(m.gamma_image(image,.8)); dark=np.asarray(m.gamma_image(image,1.2))
        self.assertTrue((bright>=np.asarray(image)).all())
        self.assertTrue((dark<=np.asarray(image)).all())
        self.assertEqual(bright.dtype,np.uint8)
        self.assertEqual(int(dark[-1,-1,0]),255)

    def test_cache_requires_exact_binary_models_and_shard_count(self):
        from types import SimpleNamespace
        run=SimpleNamespace(binary_sha256='binary',model_hashes={'model':'hash'})
        r=rows()
        key=m.referee.cache_key('binary',run.model_hashes,r,'flip',2)
        prior=dict(binary_sha256='binary',models=run.model_hashes,source_manifest_sha256='source',protocol_sha256='source',run={'flip_averaged_photo':{'cache_key':key}})
        with patch.object(m,'digest',return_value='source'):
            self.assertTrue(m.cache_eligible(run,prior,r,'flip',2)[0])
            self.assertFalse(m.cache_eligible(run,prior,r,'flip',1)[0])
            self.assertFalse(m.cache_eligible(run,dict(prior,binary_sha256='other'),r,'flip',2)[0])
            self.assertFalse(m.cache_eligible(run,dict(prior,models={'model':'changed'}),r,'flip',2)[0])


if __name__ == '__main__':
    unittest.main()
