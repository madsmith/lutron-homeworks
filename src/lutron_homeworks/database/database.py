from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
import hashlib
import logging
from xml.etree import ElementTree as ET

from .loader import LutronXMLDataLoader
from .filters import FilterLibrary, Filter
from .types import (
    LutronDBEntity,
    LutronEntity,
    LutronArea,
    LutronOutput,
    EntityType
)


class LutronDatabase:
    def __init__(self, loader: LutronXMLDataLoader):
        self._entities: dict[str, LutronDBEntity] = {}
        self._filters: list[Filter] = []
        self.logger = logging.getLogger(self.__class__.__name__)
        self.loader = loader

    def load(self):
        xml = self.loader.load_xml()
        if xml is None:
            self.logger.error("Failed to load XML data")
            return

        self._parse_xml(xml)

    def enable_filter(self, filter_name: str, args: list[str] = []):
        """ Enable a filter by name with a list of args """
        filter = FilterLibrary.get_filter(filter_name, args)
        if filter is None:
            self.logger.error(f"Filter {filter_name} not found")
            return
        
        self._filters.append(filter)

    def _apply_filters(self, entity: LutronDBEntity) -> LutronDBEntity:
        for filter in self._filters:
            entity = filter(entity)
        return entity
    
    def _hash_str(self, s: str) -> str:
        # Fold bytes into 64 bytes
        digest = hashlib.sha256(s.encode('utf-8')).digest()
        # xor bytes 0-7 with bytes 8-15 and bytes 16-23 and bytes 24-31
        folded = b''
        for i in range(8):
            folded += bytes([digest[i] ^ digest[i + 8] ^ digest[i + 16] ^ digest[i + 24]])
        
        # Return as hex
        return folded.hex()

    def _generate_area_id(self, area_element: ET.Element, parent_key: str, sibling_index: int) -> str:
        iid = area_element.get('IntegrationID')
        if iid and iid != '0':
            return iid
        key = f"{parent_key}/area[{sibling_index}]"
        return self._hash_str(key)

    def _generate_output_id(self, output_element: ET.Element, area_key: str, sibling_index: int) -> str:
        iid = output_element.get('IntegrationID')
        if iid and iid != '0':
            return iid
        key = f"{area_key}/output[{sibling_index}]"
        return self._hash_str(key)
    
    def _walk_tree(self, element: ET.Element, parent_key: str = ""):
        area_elements = element.findall("Area")
        for i, area in enumerate(area_elements):
            area_id = self._generate_area_id(area, parent_key, i)
            area_data = {
                "db_id": area_id,
                "iid": area.get("IntegrationID"),
                "name": area.get("Name"),
                "type": EntityType.AREA,
                "sort_order": area.get("SortOrder"),
                "parent_db_id": parent_key or None,
            }
            entity = LutronDBEntity.from_dict(area_data)
            entity = self._apply_filters(entity)
            self._entities[entity.db_id] = entity
            entity.with_path(self.getPath(entity.db_id))


            outputs = area.find("Outputs")
            if outputs is not None:
                for j, output in enumerate(outputs.findall("Output")):
                    output_id = self._generate_output_id(output, area_id, j)
                    output_data = {
                        "db_id": output_id,
                        "iid": output.get("IntegrationID"),
                        "name": output.get("Name"),
                        "type": EntityType.OUTPUT,
                        "subtype": output.get("OutputType"),
                        "sort_order": output.get("SortOrder"),
                        "parent_db_id": area_id,
                    }
                    entity = LutronDBEntity.from_dict(output_data)
                    entity = self._apply_filters(entity)
                    self._entities[entity.db_id] = entity
                    entity.with_path(self.getPath(entity.db_id))

            nested = area.find("Areas")
            if nested is not None:
                self._walk_tree(nested, area_id)
    
    def _parse_xml(self, xml: bytes):
        self.logger.info("Processing XML data and updating database...")
        root = ET.fromstring(xml.decode('utf-8'))

        areas_element = root.find("Areas")
        if areas_element is None:
            self.logger.error("Failed to find Areas element in XML data")
            return
        
        self._walk_tree(areas_element)

    def getEntity(self, db_id: str) -> LutronEntity:
        return self._entities[db_id]
    
    def getEntities(self) -> list[LutronEntity]:
        return list(self._entities.values())
    
    def getPath(self, db_id: str) -> list[str]:
        entity = self._entities[db_id]
        path = []
        while entity:
            path.insert(0, entity.name)
            if entity.parent_db_id is None:
                break
            entity = self._entities.get(entity.parent_db_id)
        return path
    
    def getOutputs(self) -> list[LutronOutput]:
        return [
            LutronOutput.from_entity(entity)
            for entity in self._entities.values() 
            if entity.type == EntityType.OUTPUT
        ]

    def getOutputsByIID(self, iid: int) -> LutronOutput | None:
        output = next( (
            entity
            for entity in self._entities.values()
            if entity.type == EntityType.OUTPUT and entity.iid == iid
        ), None)
        
        return LutronOutput.from_entity(output) if output else None

    def getOutputsByType(self, output_type: str) -> list[LutronOutput]:
        return [
            LutronOutput.from_entity(entity)
            for entity in self._entities.values() 
            if entity.type == EntityType.OUTPUT and entity.subtype == output_type
        ]

    def getAreas(self, parents: bool = False) -> list[LutronArea]:
        return [
            LutronArea.from_entity(entity)
            for entity in self._entities.values() 
            if entity.type == EntityType.AREA
        ]

    def getAreasById(self, area_id: int) -> LutronArea | None:
        area = next( (
            entity
            for entity in self._entities.values()
            if entity.type == EntityType.AREA and entity.iid == area_id
        ), None)
        
        return LutronArea.from_entity(area) if area else None

    def getShadeGroups(self) -> list[LutronEntity]:
        return []