"""Build source -> sdist -> wheel and exercise an isolated installed package."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    scratch = ROOT / '.release-scratch'
    scratch.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='verify-', dir=scratch))
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.setdefault('UV_CACHE_DIR', str(scratch / 'uv-cache'))
    env['UV_PYTHON_DOWNLOADS'] = 'never'
    commands = []

    def command(argv, label, expected=0):
        argv = list(map(str, argv))
        result = subprocess.run(argv, cwd=run, env=env, capture_output=True, text=True, timeout=180, check=False)
        (run / (label + '.stdout.txt')).write_text(result.stdout)
        (run / (label + '.stderr.txt')).write_text(result.stderr)
        commands.append({'label': label, 'argv': argv, 'exit_code': result.returncode})
        if result.returncode != expected:
            raise RuntimeError(label)
        if expected == 2:
            error = json.loads(result.stderr)
            assert not result.stdout and error['error'] == 'INVALID_INPUT'
            assert 'request_id' in error and str(run) not in result.stderr
        return result.stdout

    receipt = {'status': 'FAIL', 'python': sys.version, 'commands': commands,
               'remote_CI': 'NOT RUN by this local command'}
    try:
        command(['uv', 'build', ROOT, '--sdist', '--build-constraints', ROOT / 'requirements-build.txt',
                 '--out-dir', run / 'dist'], 'sdist')
        sdist, = (run / 'dist').glob('*.tar.gz')
        with tarfile.open(sdist) as archive:
            names = archive.getnames()
            for needed in ('examples/product_packet.json', 'experiments/cases.json',
                           'examples/config-base.json', 'examples/config-left.json',
                           'examples/config-right.json', 'examples/config-decisions.json',
                           'examples/config-expected.json',
                           'experiments/squad_compare.py', 'experiments/squad-protocol-v1.json',
                           'experiments/squad-pilot-v1.results.json', 'docs/assets/review-workflow.svg',
                           'docs/STABILITY.md', 'docs/RELEASING.md', 'docs/VALIDATION.md',
                           'CHANGELOG.md',
                           'requirements-dev.txt', 'scripts/verify_docs.py', 'LICENSE', 'NOTICE'):
                assert any(name.endswith('/' + needed) for name in names), needed
            assert not any(part in name.split('/') for name in names for part in
                           ('AGENTS.md', 'STATUS.md', 'LICENSE-STATUS.md', '.release-scratch'))
            archive.extractall(run / 'source', filter='data')
        source, = (run / 'source').iterdir()
        command(['uv', 'build', source, '--wheel', '--build-constraints', source / 'requirements-build.txt',
                 '--out-dir', run / 'wheel'], 'wheel')
        wheel, = (run / 'wheel').glob('*.whl')
        with zipfile.ZipFile(wheel) as archive:
            assert 'unitmerge/demo.py' in archive.namelist()
            assert 'unitmerge/reconcile.py' in archive.namelist()
            for name in ('base', 'left', 'right', 'decisions', 'expected'):
                assert any(item.endswith('/share/unitmerge/examples/config-' + name + '.json')
                           for item in archive.namelist())
            assert not any('LICENSE-STATUS' in name for name in archive.namelist())
        command(['uv', 'venv', '--python', sys.executable, run / 'venv'], 'venv')
        binary = run / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
        python = binary / ('python.exe' if os.name == 'nt' else 'python')
        command(['uv', 'pip', 'install', '--python', python, '--no-deps', '--offline', wheel], 'install')
        command([python, '-I', '-c', "import pathlib,sys,unitmerge; assert pathlib.Path(unitmerge.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())"], 'installed-import')
        command([python, '-I', '-c', "import unitmerge; assert unitmerge.__version__ == '1.1.0'"], 'installed-version')
        assert command([binary / 'unitmerge', '--version'], 'version') == 'unitmerge 1.1.0\n'
        command(['uv', 'pip', 'check', '--python', python], 'installed-dependencies')
        command([python, '-I', source / 'scripts/verify_docs.py'], 'public-docs')
        schema = run / 'schema.json'
        schema.write_text('{"type":"object"}')
        missing_extra = run / 'missing-extra-review.json'
        command([binary / 'unitmerge', 'reconcile', *([source / 'examples/config-base.json'] * 3),
                 '--schema', schema, '--report', missing_extra], 'base-missing-schema-extra', expected=2)
        assert not missing_extra.exists()
        command(['uv', 'pip', 'install', '--python', python, str(wheel) + '[schema]'],
                'install-schema-extra')
        command(['uv', 'pip', 'check', '--python', python], 'schema-dependencies')
        command([python, '-I', '-m', 'unittest', 'discover', '-s', source / 'tests', '-v'], 'installed-tests')
        demo = json.loads(command([binary / 'unitmerge', '--demo'], 'demo'))
        assert all(case['same_as_union'] for case in demo['cases'].values())
        command([binary / 'unitmerge', source / 'examples/product_packet.json'], 'unchecked-example')
        command([python, '-I', source / 'experiments/compare.py'], 'authored-comparison')
        inputs = []
        for side in ('base', 'left', 'right'):
            target = run / (side + '.json')
            target.write_bytes((source / ('examples/config-' + side + '.json')).read_bytes())
            inputs.append(target)
        review, decisions, merged = (run / name for name in
                                      ('review.json', 'decisions.json', 'merged.json'))
        decisions.write_bytes((source / 'examples/config-decisions.json').read_bytes())
        review_summary = json.loads(command([binary / 'unitmerge', 'reconcile', *inputs,
                                            '--report', review], 'config-review'))
        assert review_summary['conflicts'] == 1
        resolver = [binary / 'unitmerge', 'resolve', review, '--base', inputs[0],
                    '--left', inputs[1], '--right', inputs[2], '--decisions', decisions]
        command([*resolver, '--output', merged], 'config-resolution-second-process')
        assert json.loads(merged.read_bytes()) == json.loads(
            (source / 'examples/config-expected.json').read_bytes())
        decision_receipt = json.loads(Path(str(merged) + '.receipt.json').read_bytes())
        assert decision_receipt['output_bytes_sha256'] == hashlib.sha256(merged.read_bytes()).hexdigest()
        command([binary / 'unitmerge', 'review', review], 'config-readable-review')
        template = run / 'template.json'
        command([binary / 'unitmerge', 'decisions-template', review, '--output', template],
                'config-decisions-template')
        command([binary / 'unitmerge', 'resolve', review, '--base', inputs[0], '--left', inputs[1],
                 '--right', inputs[2], '--decisions', template, '--output', run / 'unresolved.json'],
                'config-unresolved-template', expected=2)
        command([binary / 'unitmerge', 'verify-output', merged, '--receipt',
                 Path(str(merged) + '.receipt.json')], 'config-verify-output')
        command([*resolver, '--output', merged], 'config-existing-output', expected=2)
        saved_review = review.read_bytes()
        modified_review = json.loads(saved_review)
        modified_review['conflicts'][0]['right']['value'] = 'tampered'
        review.write_text(json.dumps(modified_review))
        rejected_output = run / 'rejected.json'
        command([*resolver, '--output', rejected_output], 'config-tampered-review', expected=2)
        review.write_bytes(saved_review)
        saved_base = inputs[0].read_bytes()
        inputs[0].write_bytes(saved_base + b' ')
        command([*resolver, '--output', rejected_output], 'config-stale-bytes', expected=2)
        inputs[0].write_bytes(saved_base)
        saved_decisions = decisions.read_bytes()
        decisions.write_text('{"decisions": [], "decisions": []}')
        command([*resolver, '--output', rejected_output], 'config-malformed-decisions', expected=2)
        decisions.write_bytes(saved_decisions)
        assert not rejected_output.exists()
        receipt['practical_configuration'] = {
            'status': 'PASS', 'conflicts_reviewed': 1,
            'fixture_provenance': 'authored local configuration, hand-checked expected JSON',
            'human_usefulness': 'NOT RUN',
        }
        receipt.update(status='PASS', artifacts={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                                for path in (sdist, wheel)})
    except (AssertionError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        receipt['error'] = type(error).__name__
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'receipt': str(run / 'receipt.json')}))
    return int(receipt['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
