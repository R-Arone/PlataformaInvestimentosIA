"""A source-only distribution starts empty and handles omitted local artifacts."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import installer_builder
import model_comparison
import test_app as baseline


class PublicationTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown

    def test_fresh_database_has_no_selected_assets_or_trades(self):
        self.assertEqual(baseline.app.state()['assets'], [])
        with baseline.app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM trades').fetchone()[0], 0)
            self.assertEqual(baseline.app.settings(c)['sectors'], [])


class OptionalArtifactTests(unittest.TestCase):
    def test_historical_panel_is_unavailable_without_the_local_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(model_comparison.public_state(Path(folder), {})['status'], 'unavailable')

    def test_installer_is_unavailable_without_reviewed_packaging_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'app.py').write_text('# synthetic source\n')
            builder = installer_builder.Builder(root)
            self.assertFalse(builder.availability()[0])
            with self.assertRaises(ValueError):
                builder.start()


if __name__ == '__main__':
    unittest.main()
