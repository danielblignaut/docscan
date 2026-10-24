import copy
import json
from pathlib import Path
import tempfile
import unittest
from receipts import verify, sha
from real_study import verify_partition


class ReceiptTests(unittest.TestCase):
    def fixture(self,root):
        def put(name,value):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(value if isinstance(value,str) else json.dumps(value))
        p=dict(id='x.jpg',source='dlc',source_member='esp_id/00.re0004/000001.jpg',type='esp_id',
               number=0,clip='00.re0004',split='train',capture='android',display='lenovo',
               centre=[200.,300.],label='screen_recapture',specimen='s',identity_group='s')
        for name in ('fetch_train_only.py.acquisition-source','fetch_dlc.py.acquisition-source'):
            put(name,'# synthetic unit fixture')
        policy=dict(types=['esp_id'],positive_specimens={'train':[0]},negative_specimens={},
                    displays={'train':['lenovo']},code_sha256=sha(root/'fetch_train_only.py.acquisition-source'))
        put('policy.json',policy)
        put('source-train-lists/screen_positive_train.lst','esp_id/00.re0004/000001.jpg 200 300\n')
        put('source-train-lists/screen_negative_train.lst','')
        list_hashes={n:sha(root/'source-train-lists'/n) for n in ('screen_positive_train.lst','screen_negative_train.lst')}
        put('selection-frozen.json',dict(records=[p],list_hashes=list_hashes))
        put('members-frozen.json',dict(members={'x.jpg':{'name':'clips/images/'+p['source_member']}}))
        for name in ('midv2020-readme.txt','midv2020-license.txt','dlc-license.txt'):put(name,'unit notice')
        manifest=dict(records=[dict(**p,path='media/x.jpg')],policy_sha256=sha(root/'policy.json'),
                      members_sha256=sha(root/'members-frozen.json'))
        put('manifest.json',manifest)
        links={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
        return dict(source_train_only=True,linked_receipts=links,acquisition_manifest=manifest)

    def test_valid_receipts_without_reading_pixels(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=self.fixture(root)
            self.assertEqual(len(verify(root,s)['records']),1)
            self.assertFalse((root/'media').exists())

    def test_linked_selection_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=self.fixture(root)
            (root/'selection-frozen.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'linked receipt changed'):verify(root,s)

    def test_centre_mutation_even_if_manifest_rehashed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=self.fixture(root)
            s['acquisition_manifest']['records'][0]['centre']=[201.,300.]
            (root/'manifest.json').write_text(json.dumps(s['acquisition_manifest']))
            s['linked_receipts']['manifest.json']=sha(root/'manifest.json')
            with self.assertRaisesRegex(ValueError,'selected row/centre/split'):verify(root,s)

    def test_missing_source_list_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=self.fixture(root)
            del s['linked_receipts']['source-train-lists/screen_positive_train.lst']
            with self.assertRaisesRegex(ValueError,'missing linked receipt'):verify(root,s)

    def test_phone_and_identity_leakage(self):
        a=dict(id='a',split='train',identity_group='i',specimen='s',capture='android',label='bona_fide_capture')
        b=dict(id='b',split='dev',identity_group='j',specimen='t',capture='android',label='bona_fide_capture')
        with self.assertRaisesRegex(ValueError,'partition leak capture'):verify_partition([a,b])
        b.update(capture='iphone',identity_group='i')
        with self.assertRaisesRegex(ValueError,'partition leak identity_group'):verify_partition([a,b])

if __name__=='__main__':unittest.main()
