"""Production renderer tests from the actual repository capture, never live calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.test-render-')
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p/'data').mkdir()
        (self.p/'assets').mkdir()
        for f in ('build_site.py', 'refresh.py', 'assets/futuristic.css', 'data/data.json', 'data/whatbox.json'):
            shutil.copy2(ROOT/f, self.p/f)
        self.model = json.loads((ROOT/'data/data.json').read_text())
        self.w = json.loads((ROOT/'data/whatbox.json').read_text())
        self.run_build()

    def run_build(self, model=None, w=None, ok=True):
        (self.p/'input.json').write_text(json.dumps(self.model if model is None else model))
        (self.p/'whatbox-input.json').write_text(json.dumps(self.w if w is None else w))
        result = subprocess.run([sys.executable, str(self.p/'build_site.py'), str(self.p/'input.json'), str(self.p/'whatbox-input.json')], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return (self.p/'index.html').read_text()

    def outputs(self):
        return {f: (self.p/f).read_bytes() for f in ('index.html', 'data/data.json', 'data/whatbox.json')}

    def test_real_capture_reproducible(self):
        first = self.outputs()
        page = self.run_build()
        self.assertEqual(first, self.outputs())
        self.assertEqual(page.count('<i class="'), 95)
        self.assertIn(self.model['built'], page)
        self.assertIn('Expanded fleet capacity visuals', page)
        self.assertNotIn('<script', page)
        self.assertNotIn('STATIC DESIGN PREVIEW', page)
        self.assertNotIn('never refreshes', page)
        self.assertIn('backups/pre-futuristic-', page)

    def test_invalid_refused_without_any_output_change(self):
        for mutate in (lambda m: m['boxes'].pop(), lambda m: m['boxes'][0]['vols'].pop(next(iter(m['boxes'][0]['vols']))), lambda m: m['totals'].__setitem__('used', 1), lambda m: m['boxes'][0].__setitem__('n_disks', 23), lambda m: m['checks'].__setitem__('passed', 0)):
            with self.subTest(mutation=mutate):
                m = copy.deepcopy(self.model)
                mutate(m)
                before = self.outputs()
                self.run_build(m, ok=False)
                self.assertEqual(before, self.outputs())

    def test_invalid_whatbox_keeps_all_outputs(self):
        w = copy.deepcopy(self.w)
        w['n'] = 0
        before = self.outputs()
        self.run_build(w=w, ok=False)
        self.assertEqual(before, self.outputs())

    def test_next_capture_propagates_values_and_timestamp(self):
        m = copy.deepcopy(self.model)
        # Explicit test variation of a real captured model, not a new claimed observation.
        m['built'] = '2026-10-27T02:00:00'
        b = m['boxes'][0]
        v = next(iter(b['vols'].values()))
        v['free_tb'] -= 1
        m['totals']['used'] += 1
        b['temp'] = 41
        page = self.run_build(m)
        self.assertIn(m['built'], page)
        self.assertIn('41°C', page)
        self.assertEqual(json.loads((self.p/'data/data.json').read_text())['totals']['used'], m['totals']['used'])

    def test_private_embedded_and_exported_fields_removed(self):
        m = copy.deepcopy(self.model)
        m['boxes'][0].update(ip='192.168.0.134', password='private-fixture-secret', hostname='private-host.local')
        m['boxes'][0]['findings'].append({'sev': 'low', 'msg': 'private 10.0.0.1 and fd00::1'})
        w = copy.deepcopy(self.w)
        w['token'] = 'whatbox-fixture-secret'
        page = self.run_build(m, w)
        all_text = page + ''.join(x.decode() for x in self.outputs().values())
        for s in ('192.168.0.134', '10.0.0.1', 'fd00::1', 'private-fixture-secret', 'whatbox-fixture-secret', 'private-host.local'):
            self.assertNotIn(s, all_text)

    def test_cpu_cap_and_host_denominator_are_dynamic(self):
        w = copy.deepcopy(self.w)
        w.update(cpu_max='200000', box_cores=32)
        page = self.run_build(w=w)
        self.assertIn('CPU cap quota 200000', page)
        self.assertIn('of 32 host cores', page)
        self.assertNotIn('no CPU cap', page)
        w.pop('cpu_max')
        self.assertIn('CPU cap unknown', self.run_build(w=w))

    def test_health_tracks_arrays_and_findings_not_fixed_ids(self):
        m = copy.deepcopy(self.model)
        for b in m['boxes']:
            for v in b['vols'].values():
                v['status'] = 'normal'
            for a in b['arrays']:
                a['have'] = a['need']
            b['findings'] = []
        m['boxes'][0]['arrays'][0]['have'] -= 1
        page = self.run_build(m)
        self.assertIn('DS1 need attention', page)
        self.assertNotIn('DS2 &amp; DS4 need attention', page)

    def test_refresh_failure_keeps_whatbox_and_page(self):
        spec = importlib.util.spec_from_file_location('refresh_test', self.p/'refresh.py')
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        (self.p/'.git').mkdir()
        m = copy.deepcopy(self.model)
        m['totals']['disks'] = 1
        w = copy.deepcopy(self.w)
        w['n'] += 1
        before = self.outputs()
        with patch.object(mod, 'build_model', return_value=m), patch.object(mod, 'refresh_whatbox', return_value=w), patch.object(mod, 'log'), patch.object(sys, 'argv', ['refresh.py', '--no-push']):
            self.assertEqual(mod.main(), 1)
        self.assertEqual(before, self.outputs())
        self.assertEqual(list(self.p.glob('.refresh-*')), [])


if __name__ == '__main__':
    unittest.main()
