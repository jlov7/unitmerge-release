"""Secondary descriptor failures cannot replace the original output failure."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unitmerge import cli


class DescriptorCleanupTests(unittest.TestCase):
    def test_constructor_already_closed_descriptor_preserves_original(self):
        for error_type in (OSError, ValueError, KeyboardInterrupt):
            with self.subTest(error=error_type.__name__), tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'output'
                primary = error_type('original constructor failure')

                def failing(fd, *args, primary=primary, **kwargs):
                    os.close(fd)
                    raise primary

                with patch.object(cli.os, 'fdopen', side_effect=failing), \
                        self.assertRaises(error_type) as caught:
                    cli._open_output(path)
                self.assertIs(caught.exception, primary)
                self.assertFalse(path.exists())

    def test_open_descriptor_is_closed_when_constructor_fails(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'output'
            descriptors = []
            primary = OSError('original constructor failure')

            def failing(fd, *args, **kwargs):
                descriptors.append(fd)
                raise primary

            with patch.object(cli.os, 'fdopen', side_effect=failing), \
                    self.assertRaises(OSError) as caught:
                cli._open_output(path)
            self.assertIs(caught.exception, primary)
            self.assertFalse(path.exists())
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])

    def test_unlink_refusal_still_preserves_original_interruption(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'output'
            primary = KeyboardInterrupt('original interruption')

            def failing(fd, *args, **kwargs):
                os.close(fd)
                raise primary

            with patch.object(cli.os, 'fdopen', side_effect=failing), \
                    patch.object(Path, 'unlink', side_effect=PermissionError('refused')), \
                    self.assertRaises(KeyboardInterrupt) as caught:
                cli._open_output(path)
            self.assertIs(caught.exception, primary)
            self.assertTrue(path.exists())
            path.unlink()
