# openapi_utils.py
import streamlit as st
import json
import yaml
from openapi_spec_validator import validate_spec, exceptions as openapi_exceptions
from urllib.parse import urljoin, urlparse
from config import DEFAULT_API_BASE_URL
from utils import get_env_or_secret

@st.cache_data(show_spinner=False) # Cache spec loading and validation
def load_openapi_spec(uploaded_file):
    """Loads, parses, and validates an OpenAPI spec from an uploaded file."""
    spec = None
    error_message = None
    try:
        content_bytes = uploaded_file.read()
        uploaded_file.seek(0) # Reset pointer for potential re-reads
        # Handle potential BOM (Byte Order Mark)
        if content_bytes.startswith(b'\xef\xbb\xbf'):
             content_string = content_bytes.decode('utf-8-sig')
        else:
             content_string = content_bytes.decode('utf-8')

        file_name = uploaded_file.name.lower()
        if file_name.endswith('.json'):
            spec = json.loads(content_string)
        elif file_name.endswith(('.yaml', '.yml')):
            spec = yaml.safe_load(content_string)
        else:
            return None, "Unsupported file format. Please upload JSON or YAML."

        st.write(f"Validating OpenAPI spec: {uploaded_file.name}...")
        validate_spec(spec) # Basic structure validation
        st.write("✅ Specification structure is valid.")
        return spec, None

    except (json.JSONDecodeError, yaml.YAMLError) as e:
        error_message = f"Failed to parse spec file '{uploaded_file.name}': {e}. Check for syntax errors."
    except openapi_exceptions.OpenAPIValidationError as e:
        # More specific validation error reporting
        error_message = f"OpenAPI Schema Validation Error in '{uploaded_file.name}': {e}. Check structure/types against the OpenAPI standard."
    except UnicodeDecodeError as e:
         error_message = f"Failed to decode file '{uploaded_file.name}' as UTF-8: {e}. Ensure file encoding is correct."
    except Exception as e:
        error_message = f"Failed to load or validate spec '{uploaded_file.name}': {type(e).__name__} - {e}"

    return None, error_message


def get_base_url(spec, api_name="default"):
    """Gets the base URL from the spec servers, prioritizing HTTPS, with fallbacks.
    Always ensures the returned URL has a proper scheme (http:// or https://)."""
    base_url = None
    
    # Try to get from spec servers
    if 'servers' in spec and spec['servers']:
        https_servers = [s['url'] for s in spec['servers'] if isinstance(s, dict) and 'url' in s and isinstance(s['url'], str) and s['url'].startswith('https')]
        if https_servers:
            base_url = https_servers[0].strip('/') # Prefer first HTTPS URL, remove trailing slash
        elif spec['servers']:
            first_server = spec['servers'][0]
            if isinstance(first_server, dict) and 'url' in first_server and isinstance(first_server['url'], str):
                base_url = first_server['url'].strip('/') # Fallback to the first listed server
            else:
                st.sidebar.warning(f"⚠️ First server in spec doesn't have a valid URL property")

    # If base_url from servers doesn't have a scheme, don't use it yet
    if base_url and not (base_url.startswith('http://') or base_url.startswith('https://')):
        st.sidebar.warning(f"⚠️ Server URL in spec lacks scheme (http:// or https://)")
        # Add https:// as a default scheme
        base_url = 'https://' + base_url
        st.sidebar.info(f"Added https:// scheme to URL: {base_url}")

    # Try environment variables if no valid base_url yet or as fallback option
    env_key_specific = f'API_{api_name.upper()}_BASE_URL'
    env_key_general = 'API_BASE_URL'
    env_url = get_env_or_secret(env_key_specific) or get_env_or_secret(env_key_general)
    
    if env_url:
        # If we got an env URL, use it (it takes precedence)
        st.sidebar.info(f"Using Base URL from environment: {env_url}")
        base_url = env_url.strip('/')
    
    # In case of error with env variables, let user know
    if not env_url: 
        st.sidebar.info(f"Environment variables {env_key_specific} and {env_key_general} not found or empty.")
    
    # If still no base_url, use default
    if not base_url:
        st.sidebar.warning(f"⚠️ No valid 'servers' defined in '{api_name}' spec and no environment variables found. Using default: {DEFAULT_API_BASE_URL}")
        base_url = DEFAULT_API_BASE_URL

    # Final check to ensure we always have a scheme
    if not (base_url.startswith('http://') or base_url.startswith('https://')):
        base_url = 'https://' + base_url
        st.sidebar.info(f"Added https:// scheme to final URL: {base_url}")
        
    # For common APIs, provide specific guidance
    if 'petstore' in base_url.lower() and not 'swagger.io' in base_url.lower():
        st.sidebar.info("⚠️ Tip: For Swagger Petstore API, use 'https://petstore.swagger.io' as base URL")
    
    # Add clear debug message showing final base URL
    st.sidebar.info(f"Final base URL: {base_url}")
    
    return base_url