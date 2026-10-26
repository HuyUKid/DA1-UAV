from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from console import main, poll_controller


class ConsoleTests(unittest.TestCase):
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
                    patch('console.OffboardControl', return_value=fc) as factory, \
                    patch('console.logging.basicConfig'), patch('builtins.print'):
                self.assertEqual(main(), 0)
                self.assertIs(factory.call_args.args[2], False)
                fc.close.assert_called_once()
                fc.arm.assert_not_called()
                self.assertTrue(list(Path(tmp).glob('*.fault.log')))

    def test_invalid_configuration_is_rejected_before_connecting(self):
        for args in (['--xy-tolerance', 'nan'], ['--height', '0.5', '--z-tolerance', '0.6'],
                     ['--settle-time', '10', '--target-timeout', '5']):
            with self.subTest(args=args), patch('sys.argv', ['console.py'] + args), \
                    patch('console.OffboardControl') as factory, patch('sys.stderr'):
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
                    patch('console.wait_initial_status'), patch('console.OffboardControl', return_value=fc) as factory, \
                    patch('console.logging.basicConfig'), patch('builtins.print'):
                self.assertEqual(main(), 0)
                ownership.assert_called_once_with('udpin://127.0.0.1:14540')
                serial.assert_not_called()
                self.assertIs(factory.call_args.args[2], False)
                fc.arm.assert_not_called()
                fc.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
