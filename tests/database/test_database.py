import os
import pytest
from unittest.mock import patch

from lutron_homeworks.database.loader import LutronXMLDataLoader
from lutron_homeworks.database.database import LutronDatabase
from lutron_homeworks.database.types import (
    LutronArea,
    LutronOutput,
    EntityType
)

class TestLutronDatabase:

    @pytest.fixture
    def mock_xml_data(self) -> bytes:
        # read from current script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, "sample.xml"), "rb") as f:
            return f.read()

    @pytest.fixture
    def loader(self, tmp_path, mock_xml_data: bytes) -> LutronXMLDataLoader:
        """Create a LutronXMLDataLoader instance for testing."""
        loader = LutronXMLDataLoader(host="test.host", cache_path=str(tmp_path))
        with patch.object(loader, 'load_xml', return_value=mock_xml_data):
            yield loader

    
    @pytest.fixture
    def database(self, loader: LutronXMLDataLoader) -> LutronDatabase:
        return LutronDatabase(loader)

    def test_load(self, database: LutronDatabase):
        database.load()
        assert len(database._entities) > 0
    
    def test_get_entities(self, database: LutronDatabase):
        database.load()
        entities = database.getEntities()
        
        # Verify we get all entities
        assert len(entities) == len(database._entities)
        assert len(entities) == 27
        
        # Verify we have the correct types of entities
        entity_types = {entity.type for entity in entities}

        for entity in entities:
            print(entity)
            print(database.getPath(entity.db_id))
            
        assert EntityType.AREA in entity_types
        assert EntityType.OUTPUT in entity_types
        
    def test_get_outputs(self, database: LutronDatabase):
        database.load()
        outputs = database.getOutputs()
        
        # Verify all returned items are LutronOutput instances
        assert all(isinstance(output, LutronOutput) for output in outputs)
        
        # Verify we get the expected number of outputs from the sample XML
        # Sample XML has 20 outputs in total
        assert len(outputs) == 20
        
        # Verify some specific outputs are present
        output_names = {output.name for output in outputs}
        assert "Stairwell Chandelier 1" in output_names
        assert "Kitchen Island Lights" in output_names
        assert "Guest Ceiling Light" in output_names
        
    def test_get_outputs_by_type(self, database: LutronDatabase):
        database.load()
        outputs = database.getOutputsByType("SYSTEM_SHADE")
        
        # Verify all returned items are LutronOutput instances
        assert all(isinstance(output, LutronOutput) for output in outputs)
        
        # Verify we get the expected number of outputs from the sample XML
        # Sample XML has 8 outputs in total
        assert len(outputs) == 8
        
        # Verify some specific outputs are present
        output_names = {output.name for output in outputs}
        assert "Shade 001" in output_names
        assert "Shade 002" in output_names
        assert "Guest Room Shade" in output_names


    def test_get_outputs_by_custom_type(self, database: LutronDatabase):
        database.apply_custom_type_map({
            "shade": ["SYSTEM_SHADE"],
            "light": ["INC"]
        })

        database.load()
        outputs = database.getOutputs()

        # Verify all returned items are LutronOutput instances
        assert all(isinstance(output, LutronOutput) for output in outputs)
        
        # Verify we get the expected number of outputs from the sample XML
        # Sample XML has 8 outputs in total
        assert len(outputs) == 20

        count_shades = len([output for output in outputs if output.output_type == "SYSTEM_SHADE"])
        assert count_shades == 0

        count_lights = len([output for output in outputs if output.output_type == "INC"])
        assert count_lights == 0

        count_shades = len([output for output in outputs if output.output_type == "shade"])
        assert count_shades == 8

        count_lights = len([output for output in outputs if output.output_type == "light"])
        assert count_lights == 12
        
        # Verify some specific outputs are present
        output_names = {output.name for output in outputs}
        assert "Shade 001" in output_names
        assert "Shade 002" in output_names
        assert "Guest Room Shade" in output_names

    def test_get_areas(self, database: LutronDatabase):
        database.load()
        areas = database.getAreas()
        
        # Verify all returned items are LutronArea instances
        assert all(isinstance(area, LutronArea) for area in areas)
        
        # Verify we get the expected number of areas from the sample XML
        # Sample XML has 7 areas in total
        assert len(areas) == 7
        
        # Verify some specific areas are present
        area_names = {area.name for area in areas}
        assert "100 Main Floor" in area_names
        assert "001 Living Rom" in area_names
        assert "004 Mstr Bedroom" in area_names
        
    def test_area_name_filters(self, database: LutronDatabase):
        # Add filters before loading data
        database.enable_filter("name_replace", ["Mstr", "Master"])
        database.enable_filter("name_replace", ["2nd", "Second"])
        database.enable_filter("strip_numeric_prefix")
        database.load()
        
        areas = database.getAreas()
        area_names = {area.name for area in areas}
        print(area_names)
        
        # Check that "Mstr" has been replaced with "Master"
        assert "004 Mstr Bedroom" not in area_names
        assert "004 Master Bedroom" not in area_names
        assert "Master Bedroom" in area_names
        
        # Check that "2nd" has been replaced with "Second"
        assert "200 2nd Floor" not in area_names
        assert "200 Second Floor" not in area_names
        assert "Second Floor" in area_names
        
    def test_output_name_filters(self, database: LutronDatabase):
        # Add filter before loading data
        database.enable_filter("name_replace", ["Rec Cans", "Recessed Cans"])
        database.enable_filter("strip_numeric_suffix")
        database.load()
        
        outputs = database.getOutputs()
        output_names = {output.name for output in outputs}
        
        # Check that "Rec Cans" has been replaced with "Recessed Cans"
        assert "Stairwell Rec Cans 4" not in output_names
        assert "Stairwell Recessed Cans 4" not in output_names
        assert "Stairwell Recessed Cans" in output_names
        assert "Area Rec Cans 4" not in output_names
        assert "Area Recessed Cans 4" not in output_names
        assert "Area Recessed Cans" in output_names
