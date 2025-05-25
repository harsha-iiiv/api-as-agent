# utils.py
import os
import streamlit as st
import base64
import json
import re

def get_env_or_secret(key_name):
    """Gets a value from environment variables or Streamlit secrets, with improved error handling."""
    # First try environment variables
    value = os.getenv(key_name)
    if value:
        return value
    
    # Then try Streamlit secrets with error handling
    try:
        return st.secrets[key_name]
    except (KeyError, st.errors.StreamlitSecretNotFoundError):
        # Don't raise an error, just return None
        return None

def mask_secret(key, val):
    """Masks sensitive values like Authorization or API keys based on key name."""
    sensitive_key_fragments = ['authorization', 'api-key', 'apikey', 'secret', 'password', 'token']
    if isinstance(val, str) and any(fragment in key.lower() for fragment in sensitive_key_fragments):
        if len(val) < 8:
            return '********'
        return val[:2] + '****' + val[-2:]
    return val

def format_log_dict(d):
    """Formats a dictionary for logging, masking sensitive header/key values."""
    if not isinstance(d, dict):
        return d
    log_copy = {}
    for k, v in d.items():
        # Mask headers specifically
        if k.lower() == 'headers' and isinstance(v, dict):
            log_copy[k] = {hk: mask_secret(hk, hv) for hk, hv in v.items()}
        # Recursively mask nested dicts if they might contain secrets (optional)
        # elif isinstance(v, dict):
        #     log_copy[k] = format_log_dict(v)
        else:
            # Mask top-level keys if they look sensitive
            log_copy[k] = mask_secret(k, v)
    return log_copy

def extract_json_from_response(text):
    """Extracts the first valid JSON object from a string, handling potential markdown fences."""
    if not text: return None
    # Regex to find JSON block, potentially wrapped in ```json ... ```
    match = re.search(r"```json\s*(\{.*?\})\s*```|(\{.*?\})", text, re.DOTALL | re.IGNORECASE)
    if match:
        # Prioritize the explicitly fenced block, otherwise take the first standalone JSON
        json_str = match.group(1) if match.group(1) else match.group(2)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            st.warning(f"⚠️ Failed to parse extracted JSON: {e}\nExtracted text (first 500 chars): {json_str[:500]}...")
            return None
    st.warning(f"⚠️ No valid JSON block found in Gemini response.\nResponse (first 500 chars): {text[:500]}...")
    return None
def build_proper_api_url(base_url, path):
    """
    Properly constructs an API URL that handles version prefixes correctly.
    
    Args:
        base_url (str): The base URL, potentially including API version (e.g., 'https://example.com/api/v1')
        path (str): The endpoint path, potentially with leading slash (e.g., '/resource')
    
    Returns:
        str: Properly formatted URL that preserves API version
    """
    # Ensure both strings are valid
    if not base_url or not path:
        return None
    
    # Remove trailing slash from base_url if present
    base_url = base_url.rstrip('/')
    
    # Remove leading slash from path if present
    path = path.lstrip('/')
    
    # Check if we need to avoid path duplication
    # For example: base_url = 'https://example.com/api/v1' and path = 'api/v1/resource'
    base_path_parts = base_url.split('/')
    path_parts = path.split('/')
    
    # Find the start of any duplicated path elements
    duplicate_index = -1
    for i in range(len(base_path_parts)):
        if i >= 3:  # Skip scheme and domain parts (https://example.com)
            part = base_path_parts[i]
            if (i-3) < len(path_parts) and part == path_parts[i-3]:
                duplicate_index = i-3
                break
    
    # If we found duplication, remove it from the path
    if duplicate_index >= 0:
        path = '/'.join(path_parts[duplicate_index+1:])
    
    # Combine base URL and path
    return f"{base_url}/{path}"