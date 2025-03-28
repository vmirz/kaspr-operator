import keyword
import re
from marshmallow import fields, post_dump
from kaspr.utils.helpers import camel_to_snake
from kaspr.types.base import BaseSchema
from kaspr.types.models.tableref import TableRefSpec

def valid_param_name(name: str) -> bool:
    """
    Check if a string is a valid Python function argument name.
    
    Args:
        name (str): The string to validate.
    
    Returns:
        bool: True if the string is a valid argument name, False otherwise.
    """
    # Check if the string is empty
    if not name:
        return False
    
    # Check if the string is a Python keyword
    if keyword.iskeyword(name):
        return False
    
    # Check if the string matches the pattern for a valid Python identifier
    # Starts with a letter or underscore, followed by letters, digits, or underscores
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
    return bool(re.match(pattern, name))

class TableRefSpecSchema(BaseSchema):
    __model__ = TableRefSpec

    name = fields.String(data_key="name", required=True)
    param_name = fields.String(data_key="paramName", required=True, validate=valid_param_name)

    @post_dump
    def camelto_to_snake_dump(self, data, **kwargs):
        """Convert data keys from camelCase to snake_case."""
        return camel_to_snake(data)    