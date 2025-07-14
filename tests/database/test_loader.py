import os
import pytest
import re
import pathlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import requests

from lutron_homeworks.database.loader import LutronXMLDataLoader


class TestLutronXMLDataLoader:
    """Test suite for LutronXMLDataLoader class."""

    @pytest.fixture
    def loader(self, tmp_path):
        """Create a LutronXMLDataLoader instance for testing."""
        return LutronXMLDataLoader(host="test.host", cache_path=str(tmp_path))

    @pytest.fixture
    def mock_xml_data(self):
        """Return sample XML data for testing."""
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<Project>\n'
            b'<DbExportDate>07/09/2025</DbExportDate>\n'
            b'<DbExportTime>10:30:45</DbExportTime>\n'
            b'<Device Id="1" Name="Device1"></Device>\n'
            b'</Project>'
        )

    @pytest.fixture
    def mock_old_xml_data(self):
        """Return older sample XML data for testing."""
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<Project>\n'
            b'<DbExportDate>07/08/2025</DbExportDate>\n'
            b'<DbExportTime>10:30:45</DbExportTime>\n'
            b'<Device Id="1" Name="Device1"></Device>\n'
            b'</Project>'
        )

    def test_init(self, loader, tmp_path):
        """Test initialization of LutronXMLDataLoader."""
        assert loader.host == "test.host"
        assert loader.cache_path == str(tmp_path)

    def test_parse_export_timestamp_with_valid_xml(self, loader, mock_xml_data):
        """Test parsing export timestamp from valid XML."""
        timestamp = loader._parse_export_timestamp(mock_xml_data)
        assert timestamp == datetime(2025, 7, 9, 10, 30, 45)

    def test_parse_export_timestamp_with_bytes(self, loader, mock_xml_data):
        """Test parsing export timestamp from bytes."""
        timestamp = loader._parse_export_timestamp(mock_xml_data)
        assert timestamp == datetime(2025, 7, 9, 10, 30, 45)

    def test_parse_export_timestamp_with_string(self, loader, mock_xml_data):
        """Test parsing export timestamp from string."""
        timestamp = loader._parse_export_timestamp(mock_xml_data.decode('utf-8'))
        assert timestamp == datetime(2025, 7, 9, 10, 30, 45)

    def test_parse_export_timestamp_with_invalid_xml(self, loader):
        """Test parsing export timestamp from invalid XML."""
        invalid_xml = b'<Project><InvalidTag>test</InvalidTag></Project>'
        timestamp = loader._parse_export_timestamp(invalid_xml)
        assert timestamp is None

    def test_parse_export_timestamp_with_invalid_date_format(self, loader):
        """Test parsing export timestamp with invalid date format."""
        invalid_xml = (
            b'<Project>\n'
            b'<DbExportDate>2025/07/09</DbExportDate>\n'  # Invalid format
            b'<DbExportTime>10:30:45</DbExportTime>\n'
            b'</Project>'
        )
        timestamp = loader._parse_export_timestamp(invalid_xml)
        assert timestamp is None

    def test_load_xml_with_no_cache(self, loader, mock_xml_data):
        """Test load_xml when no cache exists."""
        # Create a simplified test focusing on behavior
        # First we'll patch exists() to return False so the cache file isn't found
        with patch('pathlib.Path.exists', return_value=False):
            # Next, we'll patch the file write operations
            m = mock_open()
            # Make sure _server_load returns our test data
            with patch.object(loader, '_server_load', return_value=mock_xml_data):
                with patch('builtins.open', m):
                    # Call the method
                    result = loader.load_xml()
        
        # Assert that the function returns the XML data from the server
        assert result == mock_xml_data
        
        # Verify that write was called with our mock data
        # We don't need to check the exact path - just that it was written
        m().write.assert_called_with(mock_xml_data)

    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_xml_with_invalid_cache(self, mock_file, mock_exists, loader, mock_xml_data):
        """Test load_xml when cache exists but is invalid."""
        mock_exists.return_value = True
        mock_file.return_value.__enter__.return_value.read.return_value = b'invalid_xml'
        
        with patch.object(loader, '_parse_export_timestamp', return_value=None) as mock_parse:
            with patch.object(loader, '_server_load', return_value=mock_xml_data):
                with patch('pathlib.Path.unlink') as mock_unlink:
                    result = loader.load_xml()
                    
        assert result == mock_xml_data
        mock_unlink.assert_called_once()
        mock_file.assert_called_with(Path(loader.cache_path) / "DbXmlInfo.xml", "wb")
        mock_file().write.assert_called_once_with(mock_xml_data)

    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_xml_with_valid_cache_newer_server(self, mock_file, mock_exists, loader, mock_xml_data, mock_old_xml_data):
        """Test load_xml when cache exists and server has newer data."""
        mock_exists.return_value = True
        mock_file_handle = mock_file.return_value.__enter__.return_value
        mock_file_handle.read.return_value = mock_old_xml_data
        
        old_timestamp = datetime(2025, 7, 8, 10, 30, 45)
        with patch.object(loader, '_parse_export_timestamp', return_value=old_timestamp) as mock_parse:
            with patch.object(loader, '_server_load', return_value=mock_xml_data) as mock_server_load:
                result = loader.load_xml()
                
                # Reset mock_parse to return the expected timestamp for the server call
                mock_parse.return_value = datetime(2025, 7, 9, 10, 30, 45)
                
        assert result == mock_xml_data
        mock_server_load.assert_called_once_with(old_timestamp)
        mock_file.assert_any_call(Path(loader.cache_path) / "DbXmlInfo.xml", "wb")
        mock_file().write.assert_called_with(mock_xml_data)

    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_xml_with_valid_cache_no_newer_server(self, mock_file, mock_exists, loader, mock_old_xml_data):
        """Test load_xml when cache exists and server doesn't have newer data."""
        mock_exists.return_value = True
        mock_file_handle = mock_file.return_value.__enter__.return_value
        mock_file_handle.read.return_value = mock_old_xml_data
        
        cache_timestamp = datetime(2025, 7, 8, 10, 30, 45)
        with patch.object(loader, '_parse_export_timestamp', return_value=cache_timestamp) as mock_parse:
            with patch.object(loader, '_server_load', return_value=None) as mock_server_load:
                result = loader.load_xml()
                
        assert result == mock_old_xml_data
        mock_server_load.assert_called_once_with(cache_timestamp)
        # Should not write to cache file since server data is not newer
        assert not any(call[0][0] == str(Path(loader.cache_path) / "DbXmlInfo.xml") 
                     and call[0][1] == "wb" for call in mock_file.call_args_list)

    @patch('requests.get')
    def test_server_load_with_newer_data(self, mock_get, loader, mock_xml_data):
        """Test _server_load when server has newer data."""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.iter_content.return_value = [mock_xml_data]
        mock_get.return_value = mock_response
        
        # Mock timestamp parsing to return a newer timestamp
        cache_timestamp = datetime(2025, 7, 8, 10, 30, 45)  # Old timestamp
        server_timestamp = datetime(2025, 7, 9, 10, 30, 45)  # New timestamp
        
        with patch.object(loader, '_parse_export_timestamp', return_value=server_timestamp):
            result = loader._server_load(cache_timestamp)
            
        assert result == mock_xml_data
        mock_get.assert_called_once_with(f"http://{loader.host}/DbXmlInfo.xml", stream=True)

    @patch('requests.get')
    def test_server_load_with_older_data(self, mock_get, loader, mock_old_xml_data):
        """Test _server_load when server has older data."""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.iter_content.return_value = [mock_old_xml_data]
        mock_get.return_value = mock_response
        
        # Mock timestamp parsing to return an older timestamp
        cache_timestamp = datetime(2025, 7, 9, 10, 30, 45)  # New timestamp
        server_timestamp = datetime(2025, 7, 8, 10, 30, 45)  # Old timestamp
        
        with patch.object(loader, '_parse_export_timestamp', return_value=server_timestamp):
            result = loader._server_load(cache_timestamp)
            
        assert result is None
        mock_get.assert_called_once_with(f"http://{loader.host}/DbXmlInfo.xml", stream=True)
        mock_response.close.assert_called_once()

    @patch('requests.get')
    def test_server_load_with_connection_error(self, mock_get, loader):
        """Test _server_load when connection fails."""
        # Set up mock response with error status
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.__enter__.return_value = mock_response
        mock_get.return_value = mock_response
        
        cache_timestamp = datetime(2025, 7, 8, 10, 30, 45)
        
        with pytest.raises(Exception, match=r"Failed to connect to lutron database:.*"):
            loader._server_load(cache_timestamp)
            
        mock_get.assert_called_once_with(f"http://{loader.host}/DbXmlInfo.xml", stream=True)
