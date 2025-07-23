from datetime import datetime
import logging
from pathlib import Path
import re
import requests

class LutronXMLDataLoader:
    def __init__(self, host: str, cache_path: str):
        """
        Initialize the LutronXMLDataLoader.
        
        Args:
            host: The Lutron server hostname or IP
            cache_path: Path where cache files will be stored
        """
        self.host = host
        self.cache_path = cache_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cache_only = False

    def set_cache_only(self, cache_only: bool):
        self._cache_only = cache_only

    def load_xml(self):
        """
        Load the XML data from the Lutron server.
        
        Returns:
            XML content as bytes or None if unavailable
        """
        try:
            # Check if the cache file exists
            cache_file = Path(self.cache_path) / "DbXmlInfo.xml"
            cache_xml = None
            cache_timestamp = None
            if cache_file.exists():
                with open(cache_file, "rb") as f:
                    cache_xml = f.read()

                cache_timestamp = self._parse_export_timestamp(cache_xml)
                if cache_timestamp is None:
                    self.logger.error("Failed to parse cache timestamp from cache XML, deleting cache")
                    cache_file.unlink()
                    cache_xml = None

            if self._cache_only:
                return cache_xml

            server_xml = self._server_load(cache_timestamp)
            if server_xml is not None:
                # Ensure cache directory exists
                cache_file.parent.mkdir(parents=True, exist_ok=True)

                with open(cache_file, "wb") as f:
                    f.write(server_xml)

                return server_xml

            return cache_xml
        except Exception as e:
            self.logger.error(f"Failed to Load XML Data: {e}")
            raise

    
    def _parse_export_timestamp(self, xml: str | bytes) -> datetime | None:
        """
        Parse the export timestamp from a chunk of XML data.
        
        Args:
            xml_chunk: A chunk of XML data as bytes or string
            
        Returns:
            datetime object if timestamp found, None otherwise
        """
        
        # Convert bytes to string if needed
        if isinstance(xml, bytes):
            xml = xml.decode('utf-8', errors='ignore')
            
        # Look for date and time patterns
        date_match = re.search(r'<DbExportDate>(\d{2}/\d{2}/\d{4})</DbExportDate>', xml)
        time_match = re.search(r'<DbExportTime>(\d{2}:\d{2}:\d{2})</DbExportTime>', xml)
        
        if date_match and time_match:
            date_str = date_match.group(1)
            time_str = time_match.group(1)
            timestamp_str = f"{date_str} {time_str}"
            
            try:
                # Parse MM/DD/YYYY HH:MM:SS format
                return datetime.strptime(timestamp_str, "%m/%d/%Y %H:%M:%S")
            except ValueError:
                self.logger.error(f"Failed to parse timestamp: {timestamp_str}")
                return None
                
        return None
    
    def _server_load(self, cache_timestamp: datetime) -> bytes | None:
        """
        Connect to the server and stream just enough data to check the timestamp.

        If the server has newer data, download and return it.
        Otherwise return None.
        
        Args:
            cache_timestamp: The timestamp of the cached data
        
        Returns:
            XML content as bytes or None if the server does not have newer data
        """
        url = f"http://{self.host}/DbXmlInfo.xml"
        with requests.get(url, stream=True) as response:
            if response.status_code != 200:
                self.logger.error(f"Failed to connect: {response.status_code}")
                raise Exception(f"Failed to connect to lutron database: {url}")

            buffer = b''
            confirmed_is_newer = False
            chunk_size = 1024

            for chunk in response.iter_content(chunk_size=chunk_size):
                buffer += chunk

                # After reading a chunk, check if we have a timestamp and if it's newer than the cache.
                # If it is not we can stop reading and return None.
                if cache_timestamp is not None and not confirmed_is_newer:
                    server_timestamp = self._parse_export_timestamp(buffer)
                    if server_timestamp:
                        if server_timestamp > cache_timestamp:
                            confirmed_is_newer = True
                        else:
                            self.logger.info(f"Local data is up to date (server: {server_timestamp}, local: {cache_timestamp})")
                            response.close()
                            return None

            response.close()
            return buffer
    