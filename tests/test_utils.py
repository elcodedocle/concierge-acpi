import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from task_executor_helper import replace_placeholders, send_wol

class TestReplacePlaceholders(unittest.TestCase):
    def test_replace_hostname_only(self):
        result = replace_placeholders("https://<hostname>/api", "server1", None)
        self.assertEqual(result, "https://server1/api")

    def test_replace_hostname_and_params(self):
        params = {"token": "abc123", "env": "prod"}
        result = replace_placeholders(
            "https://<hostname>/api?token=<token>&env=<env>",
            "server1",
            params
        )
        self.assertEqual(result, "https://server1/api?token=abc123&env=prod")

    def test_no_placeholders(self):
        result = replace_placeholders("https://example.com", "server1", None)
        self.assertEqual(result, "https://example.com")

    def test_empty_params(self):
        result = replace_placeholders("https://<hostname>/api", "server1", {})
        self.assertEqual(result, "https://server1/api")

    def test_non_string_input(self):
        result = replace_placeholders(123, "server1", None)
        self.assertEqual(result, 123)

    def test_multiple_occurrences(self):
        result = replace_placeholders("<hostname>/<hostname>", "server1", None)
        self.assertEqual(result, "server1/server1")

    def test_param_value_conversion(self):
        params = {"port": 8080, "enabled": True}
        result = replace_placeholders("host:<port>,enabled=<enabled>", "srv", params)
        self.assertEqual(result, "host:8080,enabled=True")


class TestSendWol(unittest.TestCase):
    @patch('socket.socket')
    def test_send_wol_with_colons(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        send_wol("11:22:33:44:55:66")
        
        mock_sock.setsockopt.assert_called_once()
        mock_sock.sendto.assert_called_once()
        
        # Verify packet format
        call_args = mock_sock.sendto.call_args[0]
        packet = call_args[0]
        
        # Should be 102 bytes (6 * 0xFF + 16 * 6-byte MAC)
        self.assertEqual(len(packet), 102)
        
        # First 6 bytes should be 0xFF
        self.assertEqual(packet[:6], b'\xff\xff\xff\xff\xff\xff')

    @patch('socket.socket')
    def test_send_wol_with_dashes(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        send_wol("11-22-33-44-55-66")
        
        mock_sock.sendto.assert_called_once()
        call_args = mock_sock.sendto.call_args[0]
        packet = call_args[0]
        self.assertEqual(len(packet), 102)

    @patch('socket.socket')
    def test_send_wol_broadcast_address(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        send_wol("AA:BB:CC:DD:EE:FF")
        
        call_args = mock_sock.sendto.call_args[0]
        address = call_args[1]
        self.assertEqual(address, ("255.255.255.255", 9))


if __name__ == '__main__':
    unittest.main()
