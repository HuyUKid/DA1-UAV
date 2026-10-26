"""Portable USB selection and validation must not modify the bundled model."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

HERE = Path(__file__).resolve().parents[1] / 'x500'
sys.path.insert(0, str(HERE))
import launch
from paths import serial_device
from check_setup import inspect_setup


class PortableLaunchTests(unittest.TestCase):
    def test_auto_requires_one_usb_identity(self):
        for devices in ([], [Path('/dev/serial/by-id/a'), Path('/dev/serial/by-id/b')]):
            with self.subTest(devices=devices), patch('paths.Path.glob', return_value=devices):
                with self.assertRaisesRegex(ValueError, 'use --serial'):
                    serial_device('auto')
        with patch('paths.Path.glob', return_value=[Path('/dev/serial/by-id/a')]):
            self.assertEqual(serial_device('auto'), '/dev/serial/by-id/a')

    def test_rejects_non_device_paths(self):
        for value in ('relative', '/tmp/device', '/device', '/dev/../tmp/device'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                serial_device(value)

    def test_validation_uses_temporary_usb_settings_without_changing_sources(self):
        source = HERE / 'generated/models/x500_hitl/model.sdf'
        before = source.read_bytes()
        inspected = []

        def inspect(px4, *, generated, require_device, headless):
            self.assertFalse(require_device)
            self.assertNotEqual(generated, HERE / 'generated')
            tree = E.parse(generated / 'models/x500_hitl/model.sdf')
            bridge = tree.find("model/plugin[@name='mavlink_interface']")
            self.assertEqual(bridge.findtext('serialDevice'), '/dev/null')
            self.assertEqual(bridge.findtext('baudRate'), '115200')
            inspected.append(generated)
            return {'static_errors': [], 'runtime_errors': []}

        args = ['launch.py', '--serial', '/dev/null', '--baud', '115200', '--validate']
        with patch.object(sys, 'argv', args), patch('launch.inspect_setup', side_effect=inspect), \
             patch('launch.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch('launch.subprocess.Popen') as start:
            self.assertEqual(launch.main(), 0)
            self.assertEqual(run.call_count, 2)
            start.assert_not_called()
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(inspected[0].exists())

    def test_ambiguous_usb_does_not_start_simulator(self):
        with patch.object(sys, 'argv', ['launch.py']), \
             patch('paths.Path.glob', return_value=[]), patch('launch.subprocess.Popen') as start:
            with self.assertRaises(SystemExit):
                launch.main()
            start.assert_not_called()

    def test_failed_version_command_reports_cause(self):
        failed = subprocess.CompletedProcess([], 255, '', 'Error opening log file: permission denied')
        with patch('check_setup.shutil.which', return_value='/usr/bin/gzserver'), \
             patch('check_setup.subprocess.run', return_value=failed):
            report = inspect_setup(Path('/nonexistent-px4'))
        self.assertTrue(any('permission denied' in error for error in report['runtime_errors']))
        self.assertFalse(any('modern Gazebo' in error for error in report['runtime_errors']))

    def test_classic_version_banner_with_exit_255_is_supported(self):
        version = subprocess.CompletedProcess([], 255, 'Gazebo multi-robot simulator, version 11.10.2', '')
        with patch('check_setup.shutil.which', return_value='/usr/bin/gzserver'), \
             patch('check_setup.subprocess.run', return_value=version):
            report = inspect_setup(Path('/nonexistent-px4'))
        self.assertFalse(any('version' in error.lower() for error in report['runtime_errors']))

    def test_other_gazebo_major_version_is_rejected(self):
        version = subprocess.CompletedProcess([], 255, 'Gazebo multi-robot simulator, version 9.0.0', '')
        with patch('check_setup.shutil.which', return_value='/usr/bin/gzserver'), \
             patch('check_setup.subprocess.run', return_value=version):
            report = inspect_setup(Path('/nonexistent-px4'))
        self.assertTrue(any('Classic 11 is required' in error for error in report['runtime_errors']))


if __name__ == '__main__':
    unittest.main()
