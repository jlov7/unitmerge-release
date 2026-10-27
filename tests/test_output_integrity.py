"""Failure injection at actual filesystem boundaries, without changing merge semantics."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unitmerge import cli


class OutputIntegrityTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX mode assertion')
    def test_outputs_are_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as name:
            paths = [Path(name) / 'merged.json', Path(name) / 'receipt.json']
            previous = os.umask(0)
            try:
                cli._write_new([(p, b'private configuration') for p in paths])
            finally:
                os.umask(previous)
            self.assertEqual([stat.S_IMODE(p.stat().st_mode) for p in paths], [0o600, 0o600])

    def test_close_failure_does_not_abandon_the_other_created_file(self):
        with tempfile.TemporaryDirectory() as name:
            paths = [Path(name) / 'merged.json', Path(name) / 'receipt.json']
            original_open = Path.open
            primary_error = OSError('original close failure')

            class BrokenClose:
                def __init__(self, stream):
                    self.stream = stream

                def write(self, data):
                    return self.stream.write(data)

                def close(self):
                    self.stream.close()
                    raise primary_error

            def open_fault(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return BrokenClose(stream) if path == paths[0] else stream

            # The first run exercises V1's public writer boundary. After refactoring,
            # the same physical failure is injected through the dedicated opener.
            if hasattr(cli, '_open_output'):
                opener = cli._open_output
                def secure_fault(path):
                    stream = opener(path)
                    return BrokenClose(stream) if path == paths[0] else stream
                injection = patch.object(cli, '_open_output', side_effect=secure_fault)
            else:
                injection = patch.object(Path, 'open', new=open_fault)
            with injection, self.assertRaises(OSError) as caught:
                cli._write_new([(p, b'new') for p in paths])
            self.assertIs(caught.exception, primary_error)
            self.assertFalse(any(p.exists() for p in paths))

    def test_interrupt_during_write_cleans_up_and_propagates(self):
        with tempfile.TemporaryDirectory() as name:
            paths = [Path(name) / 'merged.json', Path(name) / 'receipt.json']
            original_open = Path.open
            interrupted = KeyboardInterrupt('synthetic interrupt')

            class Interrupting:
                def __init__(self, stream):
                    self.stream = stream

                def write(self, data):
                    self.stream.write(data[:1])
                    raise interrupted

                def close(self):
                    self.stream.close()

            def open_fault(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return Interrupting(stream) if path == paths[0] else stream

            if hasattr(cli, '_open_output'):
                opener = cli._open_output
                def secure_fault(path):
                    stream = opener(path)
                    return Interrupting(stream) if path == paths[0] else stream
                injection = patch.object(cli, '_open_output', side_effect=secure_fault)
            else:
                injection = patch.object(Path, 'open', new=open_fault)
            with injection, self.assertRaises(KeyboardInterrupt) as caught:
                cli._write_new([(p, b'new') for p in paths])
            self.assertIs(caught.exception, interrupted)
            self.assertFalse(any(p.exists() for p in paths))

    def test_failed_unlink_does_not_prevent_cleanup_of_other_output(self):
        with tempfile.TemporaryDirectory() as name:
            paths = [Path(name) / 'first', Path(name) / 'second', Path(name) / 'existing']
            paths[2].write_bytes(b'preserve')
            original_unlink = Path.unlink

            def refused_unlink(path, *args, **kwargs):
                if path == paths[0]:
                    raise PermissionError('synthetic cleanup refusal')
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, 'unlink', new=refused_unlink), self.assertRaises(FileExistsError):
                cli._write_new([(p, b'new') for p in paths])
            self.assertFalse(paths[1].exists())
            self.assertEqual(paths[2].read_bytes(), b'preserve')
            # A refused unlink is not claimed repaired; remove this owned fixture.
            paths[0].unlink()

    def test_existing_symlink_and_target_are_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first, link, target = [root / p for p in ('first', 'link', 'target')]
            target.write_bytes(b'keep')
            link.symlink_to(target)
            with self.assertRaises(FileExistsError):
                cli._write_new([(first, b'new'), (link, b'new')])
            self.assertFalse(first.exists())
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b'keep')

    def test_successful_pair_remains_byte_exact(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            outputs = [(root / 'first', b'\x00\xff'), (root / 'second', b'')]
            cli._write_new(outputs)
            self.assertEqual([p.read_bytes() for p, _ in outputs], [data for _, data in outputs])
