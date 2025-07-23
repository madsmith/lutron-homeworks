import re
from typing import Any
from .types import LutronDBEntity

class Filter:
    def __init_subclass__(cls, filter_name: str, **kwargs):
        cls.filter_name = filter_name
        FilterLibrary.register_filter(cls)
        super().__init_subclass__(**kwargs)

    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        raise NotImplementedError("Subclasses must implement __call__")

class FilterLibrary:
    _filters: dict[str, type[Filter]] = {}
    
    @classmethod
    def register_filter(cls, filter_class: type[Filter]):
        cls._filters[filter_class.filter_name] = filter_class

    @classmethod
    def get_filter(cls, filter_name: str, args: list[str] = []) -> Filter | None:
        filter_class = cls._filters.get(filter_name)
        if filter_class is None:
            return None
        return filter_class(*args)

        

class NameReplaceFilter(Filter, filter_name='name_replace'):
    """
    Replace a fragment of the name with another fragment.
    """
    def __init__(self, old_fragment: str, new_fragment: str):
        self.old_fragment = old_fragment
        self.new_fragment = new_fragment
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        entity.name = entity.name.replace(self.old_fragment, self.new_fragment)
        return entity


class PreserveNumberFilter(Filter, filter_name='preserve_number'):
    """
    Replace a number (between 0 and 9) in the name with its word form.
    """
    known_numbers = {
        '0': 'Zero',
        '1': 'One',
        '2': 'Two',
        '3': 'Three',
        '4': 'Four',
        '5': 'Five',
        '6': 'Six',
        '7': 'Seven',
        '8': 'Eight',
        '9': 'Nine',
    }

    def __init__(self, name_match: str):
        self.name_match = name_match
    
    @classmethod
    def number_replacer(cls, match: re.Match) -> str:
        number = match.group(0)
        return cls.known_numbers[number] if number in cls.known_numbers else number
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        assert isinstance(entity.name, str)
        if self.name_match in entity.name:
            # Find the number in the name and replace with lookup table
            entity.name = re.sub(r'\d+', self.number_replacer, entity.name)
        return entity


class SubtypeFixFilter(Filter, filter_name='subtype_fix'):
    """
    Fix the subtype of an entity, replacing the old subtype with the new subtype if it matches the name.
    """
    def __init__(self, match_key, match_value: Any, new_subtype: str):
        self.match_key = match_key
        self.match_value = match_value
        self.new_subtype = new_subtype
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        def matches(entity: LutronDBEntity) -> bool:
            target = getattr(entity, self.match_key)
            if isinstance(self.match_value, str):
                return self.match_value in target
            return self.match_value == target

        if matches(entity):
            entity.subtype = self.new_subtype
        return entity

class TypeSuffixFilter(Filter, filter_name='type_suffix'):
    """
    Append "Shade" as a suffix to SYSTEM_SHADE outputs.
    """
    def __init__(self, output_type: str, suffix: str):
        self.output_type = output_type
        self.suffix = suffix
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        if self.output_type == entity.subtype and self.suffix not in entity.name:
            entity.name = f"{entity.name} {self.suffix}"
        return entity

class StripNumericPrefixFilter(Filter, filter_name='strip_numeric_prefix'):
    """
    Strip the numeric prefix from the name of an entity.
    """
    def __init__(self, name_match: str | None = None):
        """

        Args:
            name_match: The name to match against. If None, match against all names.
        """
        self.name_match = name_match
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        if self.name_match is None or self.name_match in entity.name:
            entity.name = re.sub(r'^\d+ *', '', entity.name)
        return entity

class StripNumericSuffixFilter(Filter, filter_name='strip_numeric_suffix'):
    """
    Strip the numeric suffix from the name of an entity.
    """
    def __init__(self, name_match: str | None = None):
        """
        Args:
            name_match: The name to match against. If None, match against all names.
        """
        self.name_match = name_match
    
    def __call__(self, entity: LutronDBEntity) -> LutronDBEntity:
        if self.name_match is None or self.name_match in entity.name:
            entity.name = re.sub(r' *\d+$', '', entity.name)
        return entity
    