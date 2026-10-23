"""The versioned fixture may extend held frames, never change source pixels."""
import tempfile
import unittest
from pathlib import Path

from make_front_back_v2 import extend


class FixtureVersionTests(unittest.TestCase):
    def test_preserves_arrivals_and_only_repeats_each_sides_held_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v1.y4m"
            output = Path(directory) / "v2.y4m"
            header = b"YUV4MPEG2 W4 H2 F30:1 Ip A0:0 C420jpeg\n"
            # Each tiny frame has a unique two-byte index plus ten filler bytes.
            frames = [b"FRAME\n" + i.to_bytes(2, "little") + bytes(10) for i in range(288)]
            original = header + b"".join(frames)
            source.write_bytes(original)
            meta = extend(source, output)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(meta["fixture_version"], 2)
            self.assertEqual(meta["frames"], 1116)
            data = output.read_bytes()
            self.assertTrue(data.startswith(header))
            actual = [data[i:i + 18] for i in range(len(header), len(data), 18)]
            self.assertEqual(actual[:144], frames[:144])
            self.assertTrue(all(f in frames[78:144] for f in actual[144:678]))
            self.assertEqual(actual[678:822], frames[144:])
            self.assertTrue(all(f in frames[222:] for f in actual[822:]))
            self.assertEqual(meta["timeline"][1]["starts_s"], 22.6)
            self.assertEqual(meta["timeline"][1]["ends_s"], 37.2)

    def test_refuses_to_replace_source_or_accept_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v1.y4m"
            source.write_bytes(b"YUV4MPEG2 W4 H2 F30:1 Ip A0:0 C420jpeg\nFRAME\n")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                extend(source, source)
            with self.assertRaisesRegex(ValueError, "two 4.8-second"):
                extend(source, Path(directory) / "v2.y4m")


if __name__ == "__main__":
    unittest.main()
