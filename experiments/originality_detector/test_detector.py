import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from detector import FEATURES, VERSION, assess, decide, extract, score
from study import validate_records, metrics, fit_logistic
from synthetic import render


class DetectorTests(unittest.TestCase):
    def model(self):
        return dict(candidate='chroma_frequency', feature_version=VERSION,
                    feature_names=FEATURES, indices=[0], mean=[0.], scale=[1.],
                    weights=[[1.], [1.]], bias=[0., 0.], thresholds=[2., 2.],
                    scope='unit fixture', deployment_validated=False)

    def test_no_original_or_fake_confidence(self):
        for logits in ([0., 0.], [5., 0.], [5., 5.], [-100., -100.]):
            p=decide(self.model(), logits, allow_experimental=True)
            self.assertIn(p['is_copy'], (None, True))
            self.assertIsNone(p['confidence'])
            self.assertNotEqual(p['status'], 'original_indicated')

    def test_no_synthetic_deployment_default(self):
        self.assertEqual(decide(self.model(), [100., 100.])['status'], 'unknown')

    def test_threshold_strict(self):
        self.assertEqual(decide(self.model(), [2., 2.], allow_experimental=True)['status'], 'unknown')
        self.assertEqual(decide(self.model(), [2.001, 2.], allow_experimental=True)['status'], 'copy_indicated')

    def test_invalid_input_abstains(self):
        for image in (np.zeros((2,2,3),np.uint8), np.zeros((100,100,4),np.uint8),
                      np.zeros((100,100,3),np.float32)):
            p=assess(self.model(), image, allow_experimental=True)
            self.assertEqual(p['status'],'unknown')

    def test_context_requires_quad(self):
        m=self.model();m['candidate']='boundary_context'
        p=assess(m,np.zeros((128,192,3),np.uint8),allow_experimental=True)
        self.assertEqual(p['status'],'unknown')
        self.assertEqual(p['detail'],'document quad required')

    def test_features_reproducible_and_schema(self):
        image,q=render(630821,9,1,'plain',[320,224])
        first=extract(image,q); second=extract(image,q)
        self.assertEqual(len(first),len(FEATURES))
        np.testing.assert_array_equal(first,second)
        self.assertTrue(np.isfinite(first).all())
        with self.assertRaises(ValueError): extract(image,[[0,0],[319,0],[319,223],[0,223]])

    def test_clean_copy_not_distinguishable(self):
        a,_=render(630821,9,1,'plain',[320,224])
        b,_=render(630821,9,1,'print_clean',[320,224])
        np.testing.assert_array_equal(a,b)

    def test_nonfinite_score_rejected(self):
        with self.assertRaises(ValueError): score(self.model(),np.full(len(FEATURES),np.nan))

    def test_no_leakage(self):
        row=dict(id='a',split='train',label='bona_fide_capture',identity='i',specimen='s',device='d')
        for key in ('identity','specimen','device'):
            second={**row,'id':'b','split':'dev','identity':'i2','specimen':'s2','device':'d2'}
            second[key]=row[key]
            with self.assertRaises(ValueError): validate_records([row,second])
        with self.assertRaises(ValueError): validate_records([{**row,'split':'test'}])

    def test_failures_stay_in_denominator(self):
        records=[dict(id='a',label='screen_recapture',specimen='a',condition='screen'),
                 dict(id='b',label='bona_fide_capture',specimen='b',condition='plain')]
        predictions=[dict(id='a',status='unknown',failure=True),dict(id='b',status='copy_indicated')]
        m=metrics(records,predictions)
        self.assertEqual((m['items'],m['attack_items'],m['negative_items'],m['failures']), (2,1,1,1))
        self.assertEqual((m['missed_or_abstained_attacks'],m['false_positives']), (1,1))
        with self.assertRaises(ValueError): metrics(records,predictions[:1])

    def test_logistic_learns_direction(self):
        x=np.arange(20,dtype=float).reshape(-1,1);y=(x[:,0]>9).astype(float)
        w,b,mean,scale=fit_logistic(x,y,dict(iterations=200,learning_rate=.1,l2=.01))
        predicted=((x-mean)/scale@w+b)>0
        self.assertTrue(np.array_equal(predicted,y.astype(bool)))

if __name__=='__main__': unittest.main()
