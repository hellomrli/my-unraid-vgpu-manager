"""The published archive must reproduce across developer and CI checkouts."""
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def test_package_is_identical_across_checkout_umasks(self):
        build = runpy.run_path(str(REPO / 'scripts/build-plugin.py'))['payload']
        with tempfile.TemporaryDirectory(prefix='vgpu-package-test-') as directory:
            checkout = Path(directory)
            source = checkout / 'source'
            shutil.copytree(REPO / 'source', source, symlinks=True)
            paths = [source, *source.rglob('*')]
            modes = {path: 0o777 if path.is_dir() or path.stat().st_mode & 0o100 else 0o666
                     for path in paths if not path.is_symlink()}
            archives = []
            with patch.dict(build.__globals__, ROOT=checkout):
                for umask in (0o022, 0o002):
                    for path, mode in modes.items():
                        path.chmod(mode & ~umask)
                    archives.append(build('2026.09.08'))
            self.assertEqual(archives[0], archives[1])


if __name__ == '__main__':
    unittest.main()
