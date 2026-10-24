import copy
import unittest
from candidates import classify, keyword_type


def words(lines):
    return [dict(text=t, x=10, y=y, w=100, h=10, line=i) for i, (y, t) in enumerate(lines)]

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(mode='explicit_title', header_fraction=.25, max_line_words=12)

    def test_transaction_decoys_do_not_override_title(self):
        page = words([(20, 'BANK STATEMENT'), (500, 'water electricity water insurance premium')])
        self.assertEqual(classify(page, [800, 1000], 'utility_bill', self.config), 'bank_statement')

    def test_lower_page_title_does_not_trigger(self):
        self.assertEqual(classify(words([(700, 'bank statement')]), [800, 1000], 'other', self.config), 'other')

    def test_ambiguous_title_abstains(self):
        page = words([(20, 'bank statement'), (70, 'rental agreement')])
        self.assertEqual(classify(page, [800, 1000], 'other', self.config), 'other')

    def test_word_boundary_and_input_immutability(self):
        page = words([(20, 'bank statements')]); before = copy.deepcopy(page)
        self.assertEqual(classify(page, [800, 1000], 'other', self.config), 'other')
        self.assertEqual(page, before)

    def test_missing_geometry_and_empty_words(self):
        self.assertEqual(classify([], None, 'other', self.config), 'other')

    def test_shipped_tie_and_lease_weight(self):
        self.assertEqual(keyword_type('water bank statement'), 'utility_bill')
        self.assertEqual(keyword_type('lease water'), 'lease_agreement')

    def test_long_paragraph_does_not_trigger(self):
        page = words([(20, 'please supply a bank statement and enough additional words to make a long paragraph exceed the limit')])
        self.assertEqual(classify(page, [800, 1000], 'other', self.config), 'other')

if __name__ == '__main__':
    unittest.main()
