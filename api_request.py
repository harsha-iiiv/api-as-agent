# api_request.py
import requests
import json
from urllib.parse import urljoin, urlparse
from utils import get_env_or_secret # Needed for query API keys
from config import REQUEST_TIMEOUT_SECONDS

def build_request_details(op, path, method, user_values, spec, auth_headers, api_name):
    """
    Builds query parameters, headers, path params and identifies body schema/content type.
    Returns: (query_params, headers, path_params, body_schema, body_content_type) tuple.
    """
    query_params = {}
    headers = auth_headers.copy() # Start with authentication headers
    path_params = {} # Store path parameters separately
    body_schema = None
    body_content_type = None

    # --- Handle Parameters defined in OpenAPI spec ---
    param_definitions = op.get('parameters', []) if isinstance(op, dict) else []
    for param in param_definitions:
        if not isinstance(param, dict): continue
        p_name = param.get('name')
        p_location = param.get('in')
        if not p_name or not p_location: continue

        # Get value from user_values (which might come from Gemini or manual input)
        p_value = user_values.get(p_name)

        # Include param if value is provided (non-None, potentially empty string is ok based on schema/required?)
        # Let's include if not None for now. Empty strings might be valid for some params.
        if p_value is not None:
            if p_location == 'query':
                query_params[p_name] = p_value
            elif p_location == 'header':
                headers[p_name] = p_value
            elif p_location == 'path':
                path_params[p_name] = p_value
            # 'cookie' params are not handled here

    # --- Handle API Key in Query (if applicable) ---
    # Check security schemes for query-based API keys not handled by auth.py headers
    if 'components' in spec and 'securitySchemes' in spec['components']:
        schemes = spec['components']['securitySchemes']
        security_req_list = spec.get('security', [{}])
        found_query_key = False
        for security_reqs in security_req_list:
            if found_query_key: break
            for name in security_reqs.keys():
                if name not in schemes: continue
                sec = schemes[name]
                if sec.get('type') == 'apiKey' and sec.get('in') == 'query':
                    key_env = f'APIKEY_{name.upper()}'
                    key = get_env_or_secret(key_env)
                    api_key_name = sec.get('name')
                    if key and api_key_name:
                        query_params[api_key_name] = key
                        found_query_key = True
                        break # Assume only one query API key needed per req set

    # --- Handle Request Body ---
    request_body_spec = op.get('requestBody') if isinstance(op, dict) else None
    if isinstance(request_body_spec, dict) and 'content' in request_body_spec:
        content = request_body_spec['content']
        # Common content types, ordered by preference
        preferred_ctypes = ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data', '*/*']
        for ctype in preferred_ctypes:
            if ctype in content and isinstance(content[ctype], dict) and 'schema' in content[ctype]:
                body_schema = content[ctype]['schema']
                body_content_type = ctype
                break
            # Handle wildcard match if no specific preferred type found
            if ctype == '*/*' and content:
                 first_available_ctype = list(content.keys())[0]
                 if isinstance(content[first_available_ctype], dict) and 'schema' in content[first_available_ctype]:
                      body_schema = content[first_available_ctype]['schema']
                      body_content_type = first_available_ctype
                      break

    return query_params, headers, path_params, body_schema, body_content_type


def execute_api_call(method, url, headers, query_params, body_data, content_type):
    """
    Executes the API call using the requests library.
    Returns a tuple: (response_object, error_message)
    """
    response = None
    error = None
    
    # Debug logging of URL before request
    print(f"DEBUG: Making request to URL: {url}")
    
    # Ensure URL has a valid scheme
    if not url.startswith('http://') and not url.startswith('https://'):
        error = f"Invalid URL format: {url}. URL must include http:// or https:// scheme."
        print(f"ERROR: {error}")
        return None, error
    
    request_args = {
        'method': method.upper(),
        'url': url,
        'headers': headers,
        'timeout': REQUEST_TIMEOUT_SECONDS
    }

    # Add params/data/json based on method and content type
    if method.lower() in ['get', 'head', 'delete'] and query_params:
         request_args['params'] = query_params
    elif method.lower() not in ['get', 'head', 'delete']:
         if query_params: # Sometimes APIs use query params with POST/PUT etc.
              request_args['params'] = query_params
         if body_data:
             if content_type == 'application/json':
                 request_args['json'] = body_data
             elif content_type == 'application/x-www-form-urlencoded':
                 request_args['data'] = body_data # requests handles form encoding
             else:
                 # For multipart/form-data, files would need special handling
                 # For generic data, assume it's a string or bytes
                 request_args['data'] = json.dumps(body_data) if isinstance(body_data, dict) else body_data
                 # Ensure Content-Type header is set if sending data/json
                 if 'Content-Type' not in headers and 'content-type' not in headers:
                      headers['Content-Type'] = content_type if content_type else 'application/octet-stream'
                      request_args['headers'] = headers # Update headers in args

    try:
        response = requests.request(**request_args)
        # Raise HTTPError for bad responses (4xx or 5xx) - optional, handled in main loop now
        # response.raise_for_status()
    except requests.exceptions.Timeout:
       error = f"Connection timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
    except requests.exceptions.RequestException as e:
       error = f"{type(e).__name__}: {e}"
    except Exception as e:
       error = f"Unexpected error during request: {type(e).__name__} - {e}"

    return response, error

def build_curl_command(method, url, headers, query_params, body_data, content_type):
    """Builds an equivalent cURL command string."""
    try:
        curl_parts = [f"curl -X {method.upper()}"]

        # Add query params directly to URL for cURL simplicity? Or use --get with -d?
        # Let's add to URL for broad compatibility
        url_with_params = url
        if query_params:
             # Use requests internal encoding for consistency
             query_string = requests.compat.urlencode(query_params)
             separator = '&' if '?' in url else '?'
             url_with_params = f"{url}{separator}{query_string}"
        curl_parts.append(f"'{url_with_params}'") # Add URL in quotes

        for hk, hv in headers.items():
            # Escape single quotes in header values for shell safety
            hv_escaped = str(hv).replace("'", "'\\''")
            curl_parts.append(f"-H '{hk}: {hv_escaped}'")

        if body_data and method.lower() not in ['get', 'delete', 'head']:
            body_str = None
            # Add content-type header if not already present and needed
            if 'content-type' not in (h.lower() for h in headers):
                 detected_ctype = content_type if content_type else 'application/json' # Default assumption
                 curl_parts.append(f"-H 'Content-Type: {detected_ctype}'")

            # Format body based on common types
            effective_ctype = headers.get('Content-Type', headers.get('content-type', content_type))
            if effective_ctype and 'json' in effective_ctype.lower():
                 body_str = json.dumps(body_data)
            elif effective_ctype and 'x-www-form-urlencoded' in effective_ctype.lower():
                 # urlencode needs dict, not string
                 body_str = requests.compat.urlencode(body_data) if isinstance(body_data, dict) else str(body_data)
            else: # Default: treat as string/raw data
                 body_str = json.dumps(body_data) if isinstance(body_data, dict) else str(body_data)

            # Escape single quotes in body for shell safety
            body_escaped = body_str.replace("'", "'\\''")
            curl_parts.append(f"--data '{body_escaped}'")

        return " \\\n  ".join(curl_parts) # Join with line continuation for readability
    except Exception as curl_err:
        print(f"Could not generate cURL command: {curl_err}")
        return f"# Error generating cURL: {curl_err}"