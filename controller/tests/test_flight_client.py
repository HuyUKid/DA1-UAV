"""Tests for the local Flight Service supervisory console; no MAVSDK access."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))

from flight.client import COMMANDS, build_request, interactive, main


class FlightClientTests(unittest.TestCase):
    def test_build_request_maps_terminal_names_to_web_commands(self):
        self.assertEqual(build_request('status'), {'op': 'status'})
        for terminal_name, command_type in COMMANDS.items():
            with self.subTest(command=terminal_name):
                request = build_request(terminal_name)
                self.assertEqual(request['op'], 'command')
                self.assertEqual(request['command']['type'], command_type)
                self.assertTrue(request['command']['command_id'].startswith('local-'))
                self.assertEqual(request['command']['mission_id'], 'local-supervision')
                expected = {'confirm_force': True} if terminal_name == 'disarm' else {}
                self.assertEqual(request['command']['params'], expected)

    def test_emergency_disarm_is_immediate_and_sets_force_parameter(self):
        client = Mock()
        client.request.return_value = {'ok': True}
        commands = iter(['disarm', 'exit'])
        output = []

        self.assertEqual(interactive(client, input_fn=lambda _: next(commands),
                                     output=output.append), 0)
        self.assertEqual(client.request.call_count, 1)
        command = client.request.call_args.args[0]['command']
        self.assertEqual(command['type'], 'disarm')
        self.assertEqual(command['params'], {'confirm_force': True})
        self.assertTrue(any('EMERGENCY MOTOR STOP' in line for line in output))

    def test_one_shot_disarm_sends_immediately(self):
        with patch('flight.client.RpcClient') as client, patch('builtins.print'):
            client.return_value.request.return_value = {'ok': True}
            self.assertEqual(main(['disarm']), 0)
            command = client.return_value.request.call_args.args[0]['command']
            self.assertEqual(command['type'], 'disarm')
            self.assertEqual(command['params'], {'confirm_force': True})

    def test_interactive_sends_simple_commands_and_exit_does_not_land(self):
        client = Mock()
        client.request.return_value = {'ok': True}
        commands = iter(['pause', 'resume', 'return-home', 'exit'])
        output = []

        self.assertEqual(interactive(client, input_fn=lambda _: next(commands),
                                     output=output.append), 0)
        sent_types = [call.args[0]['command']['type']
                      for call in client.request.call_args_list]
        self.assertEqual(sent_types, ['pause', 'resume', 'return_home'])
        self.assertNotIn('land', sent_types)
        self.assertIn('no LAND command was sent', output[-1])

    def test_no_argument_opens_interactive_console(self):
        with patch('flight.client.interactive', return_value=0) as shell, \
                patch('flight.client.RpcClient') as client:
            self.assertEqual(main([]), 0)
        shell.assert_called_once_with(client.return_value)


if __name__ == '__main__':
    unittest.main()
