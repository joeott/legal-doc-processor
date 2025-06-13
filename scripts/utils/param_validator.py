"""Lightweight parameter validation for Celery tasks"""

import inspect
import logging
from typing import Union, Optional, Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)

def normalize_uuid_param(value: Union[str, dict, object]) -> str:
    """
    Normalize various UUID input formats to string.
    
    Handles:
    - String UUIDs (pass through)
    - Dict with 'document_uuid' key
    - UUID objects with .hex attribute
    - Any other object (convert to string)
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, dict):
        # Handle dict parameters (Celery serialization issue)
        if 'document_uuid' in value:
            logger.debug(f"Extracting UUID from dict: {value.get('document_uuid')}")
            return str(value['document_uuid'])
        else:
            # Try to find any key with 'uuid' in it
            for key, val in value.items():
                if 'uuid' in key.lower():
                    logger.debug(f"Found UUID in dict key '{key}': {val}")
                    return str(val)
            raise ValueError(f"No UUID found in dict: {value}")
    elif hasattr(value, 'hex'):
        # UUID object
        logger.debug(f"Converting UUID object to string: {value}")
        return str(value)
    else:
        # Last resort - convert to string
        logger.debug(f"Converting unknown type {type(value).__name__} to string: {value}")
        return str(value)

def normalize_file_path(value: Union[str, dict]) -> str:
    """
    Normalize file path parameter.
    
    Handles:
    - String paths (pass through)
    - Dict with 'file_path' or 's3_url' keys
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, dict):
        # Try common keys
        for key in ['file_path', 's3_url', 'path', 'url']:
            if key in value:
                logger.debug(f"Extracting file path from dict key '{key}': {value[key]}")
                return str(value[key])
        raise ValueError(f"No file path found in dict: {value}")
    else:
        return str(value)

def validate_task_params(expected_types: Dict[str, type] = None):
    """
    Decorator for parameter validation and normalization.
    
    Features:
    - Automatic UUID parameter normalization
    - Type logging for debugging
    - Graceful handling of parameter variations
    
    Usage:
        @validate_task_params({'document_uuid': str, 'file_path': str})
        def my_task(document_uuid: str, file_path: str):
            # Parameters are normalized
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get function signature
            sig = inspect.signature(func)
            
            # Skip 'self' for bound methods
            params = list(sig.parameters.keys())
            if params and params[0] == 'self':
                params = params[1:]
                # Keep self in args
                self_arg = args[0] if args else None
                args = args[1:] if args else ()
            else:
                self_arg = None
            
            # Build argument dictionary
            bound_args = {}
            
            # Handle positional arguments
            for i, (param_name, arg_value) in enumerate(zip(params, args)):
                bound_args[param_name] = arg_value
            
            # Handle keyword arguments
            bound_args.update(kwargs)
            
            # Log original parameter types if debug mode
            if logger.isEnabledFor(logging.DEBUG) or os.getenv('PARAMETER_DEBUG', '').lower() == 'true':
                logger.info(f"Task {func.__name__} received parameters:")
                for param_name, value in bound_args.items():
                    logger.info(f"  {param_name}: {type(value).__name__} = {repr(value)[:100]}")
            
            # Normalize parameters
            normalized_args = {}
            for param_name, value in bound_args.items():
                # Special handling for UUID parameters
                if param_name.endswith('_uuid') or param_name == 'document_id':
                    try:
                        normalized_args[param_name] = normalize_uuid_param(value)
                        if value != normalized_args[param_name]:
                            logger.debug(f"Normalized {param_name}: {type(value).__name__} -> str")
                    except Exception as e:
                        logger.error(f"Failed to normalize UUID parameter {param_name}: {e}")
                        raise
                
                # Special handling for file paths
                elif param_name in ['file_path', 's3_url', 'document_path']:
                    try:
                        normalized_args[param_name] = normalize_file_path(value)
                        if value != normalized_args[param_name]:
                            logger.debug(f"Normalized {param_name}: {type(value).__name__} -> str")
                    except Exception as e:
                        logger.error(f"Failed to normalize file path parameter {param_name}: {e}")
                        raise
                
                # Pass through other parameters
                else:
                    normalized_args[param_name] = value
            
            # Rebuild args for function call
            if self_arg is not None:
                # Include self for bound methods
                new_args = [self_arg] + [normalized_args.get(p) for p in params if p in normalized_args]
                # Remove from kwargs to avoid duplicate
                new_kwargs = {k: v for k, v in normalized_args.items() if k not in params}
            else:
                new_args = [normalized_args.get(p) for p in params if p in normalized_args]
                new_kwargs = {k: v for k, v in normalized_args.items() if k not in params}
            
            # Call function with normalized parameters
            return func(*new_args, **new_kwargs)
            
        return wrapper
    return decorator

# Import os at module level
import os