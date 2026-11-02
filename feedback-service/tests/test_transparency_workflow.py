"""Exercise checkpoint restore failure handling using the workflow's shell step."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest


def bash_path():
    if os.name == 'nt':
        git = shutil.which('git')
        candidate = Path(git).parent.parent / 'bin' / 'bash.exe' if git else None
        return str(candidate) if candidate and candidate.exists() else None
    return shutil.which('bash')


@unittest.skipUnless(bash_path(), 'Bash is required to exercise the Actions shell step')
class CheckpointRestoreTests(unittest.TestCase):
    def restore(self, failure=''):
        workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'transparency.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Restore and verify previous checkpoint\n', 1)[1].split('      - name:', 1)[0]
        commands = textwrap.dedent(step.split('        run: |\n', 1)[1])
        # Stubs replace remote reads and verification tools, never project source.
        # Bash -e matches the Actions runner: later work must not follow a failure.
        stubs = '''
git() {
  if [ "$1" = fetch ]; then
    [ "$FAILURE" != fetch ] || return 17
  elif [ "$1" = show ]; then
    [ "$FAILURE" != "${2#*:}" ] || return 18
    printf '{}\\n'
  else
    return 19
  fi
}
cosign() { [ "$FAILURE" != signature ] || return 20; }
python() { [ "$FAILURE" != checkpoint ] || return 21; }
'''
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            return subprocess.run(
                [bash_path(), '--noprofile', '--norc', '-eo', 'pipefail', '-c', stubs + commands + "printf 'RESTORE_COMPLETE\\n'"],
                cwd=directory, env={**os.environ, 'PUBLIC_KEY': 'fixture-public-key', 'FAILURE': failure},
                capture_output=True, text=True, timeout=15)

    def assert_stopped(self, failure):
        result = self.restore(failure)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('RESTORE_COMPLETE', result.stdout)

    def test_verified_history_allows_next_step(self):
        result = self.restore()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESTORE_COMPLETE', result.stdout)

    def test_fetch_failure_stops_restore(self):
        self.assert_stopped('fetch')

    def test_missing_journal_stops_restore(self):
        self.assert_stopped('journal.jsonl')

    def test_missing_checkpoint_stops_restore(self):
        self.assert_stopped('checkpoint.json')

    def test_missing_bundle_stops_restore(self):
        self.assert_stopped('checkpoint.sigstore.json')

    def test_signature_failure_stops_restore(self):
        self.assert_stopped('signature')

    def test_checkpoint_mismatch_stops_restore(self):
        self.assert_stopped('checkpoint')
