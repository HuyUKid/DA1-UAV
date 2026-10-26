"""Distribution regressions: the bundle must work without a PX4 checkout."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'x500'))
from paths import plugin_directory
from prebuilt import bundle_errors


class PrebuiltTests(unittest.TestCase):
    def setUp(self):
        self.bundle = HERE / 'prebuilt/ubuntu-22.04-x86_64'
        self.host = patch('prebuilt.platform.freedesktop_os_release',
                          return_value={'ID': 'ubuntu', 'VERSION_ID': '22.04'})
        self.machine = patch('prebuilt.platform.machine', return_value='x86_64')
        self.host.start()
        self.machine.start()
        self.addCleanup(self.host.stop)
        self.addCleanup(self.machine.stop)

    def test_shipped_bundle_matches_manifest_and_contains_every_model_plugin(self):
        self.assertEqual(bundle_errors(self.bundle / 'lib'), [])
        model = E.parse(HERE / 'x500/generated/models/x500_hitl/model.sdf')
        plugins = {p.get('filename') for p in model.findall('.//plugin')}
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        self.assertEqual(plugins, set(manifest['model_plugins']))
        self.assertTrue(plugins <= set(manifest['libraries']))

    def test_default_uses_bundle_without_looking_for_px4_source(self):
        with patch('paths.default_px4', side_effect=AssertionError('PX4 source must not be required')):
            self.assertEqual(plugin_directory(), self.bundle / 'lib')
        source = Path('/explicit-source')
        self.assertEqual(plugin_directory(source), source / 'build/px4_sitl_default/build_gazebo-classic')

    def test_changed_or_missing_sibling_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle'
            shutil.copytree(self.bundle, bundle)
            path = bundle / 'lib/libmav_msgs.so'
            path.write_bytes(path.read_bytes() + b'changed')
            self.assertTrue(any('checksum mismatch: libmav_msgs.so' in e for e in bundle_errors(bundle / 'lib')))
            path.unlink()
            self.assertTrue(any('Missing bundled library: libmav_msgs.so' in e for e in bundle_errors(bundle / 'lib')))

    def test_incompatible_host_is_rejected(self):
        with patch('prebuilt.platform.machine', return_value='aarch64'):
            self.assertTrue(any('Ubuntu 22.04 x86_64' in e for e in bundle_errors(self.bundle / 'lib')))
        with patch('prebuilt.platform.freedesktop_os_release', return_value={'ID': 'ubuntu', 'VERSION_ID': '24.04'}):
            self.assertTrue(any('Ubuntu 22.04 x86_64' in e for e in bundle_errors(self.bundle / 'lib')))


if __name__ == '__main__':
    unittest.main()
