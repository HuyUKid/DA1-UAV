from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from console import execute, main, parse_command, poll_controller


class ConsoleTests(unittest.TestCase):
    def test_gps_commands_are_explicit_and_plan_never_starts_implicitly(self):
        line = 'gps-plan 10 106.00002 10 106.00005 2.5 0.4'
        self.assertEqual(parse_command(line),
                         ('gps-plan', (10.0, 106.00002, 10.0, 106.00005, 2.5, 0.4)))
        fc = Mock()
        fc.gps_plan.return_value = {'leg_m': 5.5}
        execute(fc, line, output=lambda _: None)
        fc.gps_plan.assert_called_once_with(10.0, 106.00002, 10.0, 106.00005, 2.5, 0.4)
        fc.gps_start.assert_not_called()
        self.assertEqual(parse_command('gps-start'), ('gps-start', None))
        for command in ('pause', 'resume', 'cancel'):
            self.assertEqual(parse_command(command), (command, None))
            execute(fc, command, output=lambda _: None)
            getattr(fc, command).assert_called_once()
        for invalid in ('gps-plan 10 106', 'gps-plan nan 106 10 106.00005 2 0.4'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_command(invalid)
        for old_alias in ('gps-pause', 'gps-resume', 'gps-cancel'):
            with self.subTest(old_alias=old_alias), self.assertRaises(ValueError):
                parse_command(old_alias)

    def test_return_home_command_dispatches_without_auto_land(self):
        self.assertEqual(parse_command('return-home'), ('return-home', None))
        self.assertEqual(parse_command('return-height'), ('return-height', None))
        fc = Mock()
        execute(fc, 'return-home', output=lambda _: None)
        fc.return_home.assert_called_once()
        execute(fc, 'return-height', output=lambda _: None)
        fc.return_height.assert_called_once()
        fc.land.assert_not_called()
        with self.assertRaises(ValueError):
            parse_command('rtl')

    def test_polling_failure_keeps_sdk_alive_for_land(self):
        fc = Mock()
        fc.refresh.side_effect = RuntimeError('native teardown failed')
        logger = Mock()
        poll_controller(fc, logger, include_status=True)
        logger.exception.assert_called_once()
        fc.close.assert_not_called()
        self.assertIn('Polling failed', fc.last_error)

    def test_check_never_enables_actuation_even_when_flag_is_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            fc = Mock()
            fc.status.return_value = {'connected': True}
            with patch('sys.argv', ['console.py', '--check', '--enable-actuation',
                                    '--profile', 'hardware', '--log-dir', tmp]), \
                    patch('console.validate_connection', return_value='/dev/fake'), \
                    patch('console.serial_ownership'), \
                    patch('console.wait_initial_status'), \
            patch('console.GpsMissionControl', return_value=fc) as factory, \
                    patch('console.logging.basicConfig'), patch('builtins.print'):
                self.assertEqual(main(), 0)
                self.assertIs(factory.call_args.args[2], False)
                fc.close.assert_called_once()
                fc.arm.assert_not_called()
                self.assertTrue(list(Path(tmp).glob('*.fault.log')))

    def test_invalid_configuration_is_rejected_before_connecting(self):
        for args in (['--xy-tolerance', 'nan'], ['--height', '0.5', '--z-tolerance', '0.6'],
                     ['--settle-time', '10', '--target-timeout', '5'],
                     ['--height', '4', '--gps-max-height', '3']):
            with self.subTest(args=args), patch('sys.argv', ['console.py'] + args), \
                patch('console.GpsMissionControl') as factory, patch('sys.stderr'):
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                factory.assert_not_called()

    def test_pc_hitl_check_uses_udp_lock_without_enabling_actuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fc = Mock()
            fc.status.return_value = {'connected': True}
            with patch('sys.argv', ['console.py', '--check', '--enable-actuation', '--profile', 'hitl',
                                    '--connection', 'udpin://127.0.0.1:14540', '--log-dir', tmp]), \
                    patch('console.udp_ownership') as ownership, patch('console.serial_ownership') as serial, \
            patch('console.wait_initial_status'), patch('console.GpsMissionControl', return_value=fc) as factory, \
                    patch('console.logging.basicConfig'), patch('builtins.print'):
                self.assertEqual(main(), 0)
                ownership.assert_called_once_with('udpin://127.0.0.1:14540')
                serial.assert_not_called()
                self.assertIs(factory.call_args.args[2], False)
                fc.arm.assert_not_called()
                fc.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
