"""Focused invariants for the optional raw-block experiment (no dataset fixtures)."""
import copy
import unittest

from stress_rawblock import canonical_ocr_words, select


def words(lines):
    return canonical_ocr_words([dict(text=t, x=x, y=y, w=100, h=10) for x,y,t in lines])


class GroundingTests(unittest.TestCase):
    def test_no_label_abstains(self):
        self.assertEqual(select(words([(20,20,'Example Person')]), [500,700]),
                         dict(status='no_label', indices=[]))

    def test_multiple_labels_conflict(self):
        self.assertEqual(select(words([(20,20,'Bill to:'),(20,40,'Recipient:')]), [500,700])['status'], 'conflict')

    def test_preserves_source_indices_and_input(self):
        source = words([(20,80,'Total: 20'),(20,20,'Bill to:'),(20,40,'Example Person'),(20,60,'12 Example Road')])
        before = copy.deepcopy(source)
        actual = select(source,[500,700])
        self.assertEqual([source[i]['text'] for i in actual['indices']], ['Example','Person','12','Example','Road'])
        self.assertEqual(source,before)
        self.assertEqual(actual['indices'],[4,5,6,7,8])

    def test_same_line_suffix(self):
        source=words([(20,20,'Recipient: Example Person')])
        self.assertEqual(select(source,[500,700])['indices'], [1,2])

    def test_distant_block_not_selected(self):
        self.assertEqual(select(words([(20,20,'Bill to:'),(20,150,'Example Person')]), [500,700])['status'], 'no_adjacent_text')

    def test_two_geometric_continuations_conflict(self):
        source=words([(20,20,'Bill to:'),(20,40,'Person One'),(80,40,'Person Two')])
        self.assertEqual(select(source,[500,700])['status'],'conflict')

    def test_no_cross_column_jump(self):
        source=words([(20,20,'Bill to:'),(300,40,'Example Person')])
        self.assertEqual(select(source,[500,700])['indices'],[])

    def test_canonical_source_offsets(self):
        text='  Example   Person '
        source=words([(20,20,text)])
        for w in source:
            self.assertEqual(text[w['char_start']:w['char_end']],w['text'])
            self.assertEqual(w['source_line_index'],0)
            self.assertEqual((w['x'],w['w']),(20,100))

    def test_invalid_geometry(self):
        self.assertEqual(select([], [0,700])['status'], 'invalid_geometry')

    def test_bounded_output_is_explicitly_null(self):
        source=words([(20,20,'Bill to:')]+[(20,40+20*i,'Example') for i in range(8)])
        self.assertEqual(select(source,[500,700]),dict(status='limit',indices=[]))


if __name__ == '__main__':
    unittest.main()
