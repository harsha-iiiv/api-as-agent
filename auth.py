import streamlit as st
import requests
import base64
from urllib.parse import urljoin, urlparse
from utils import get_env_or_secret
from config import REQUEST_TIMEOUT_SECONDS
# Import get_base_url directly to avoid circular dependency if it were moved here
from openapi_utils import get_base_url

@st.cache_data(ttl=600, show_spinner=False) # Cache auth results for 10 mins
def get_auth_headers(spec, api_name):
    """Gets authentication headers based on securitySchemes defined in the spec.
       Returns a tuple: (headers_dict, unique_error_list)
    """
    headers = {}
    auth_errors = []
    if not spec or 'components' not in spec or 'securitySchemes' not in spec['components']:
        st.sidebar.info(f"ℹ️ No securitySchemes found in '{api_name}'. Assuming no auth required.")
        return {}, []

    schemes = spec['components']['securitySchemes']
    security_req_list = spec.get('security', [{}]) # List of security requirement objects (OR logic)

    obtained_auth = False
    for security_reqs in security_req_list: # Iterate through OR conditions
        if obtained_auth: break

        current_req_headers = {}
        all_reqs_met_in_set = True # Assume true for this AND set initially
        schemes_to_try_in_req = list(security_reqs.keys())

        # If security obj is empty {} or [], try the first defined scheme as a fallback
        if not schemes_to_try_in_req and schemes:
             schemes_to_try_in_req = [list(schemes.keys())[0]]

        for name in schemes_to_try_in_req:
            if name not in schemes:
                auth_errors.append(f"Auth Error ({name}): Scheme defined in 'security' section but not found in 'components.securitySchemes'.")
                all_reqs_met_in_set = False; break
            if not all_reqs_met_in_set: break # Stop processing this set if one scheme fails

            sec = schemes[name]
            auth_successful_for_scheme = False
            try:
                # --- OAuth2 Client Credentials ---
                if sec.get('type') == 'oauth2' and sec.get('flows', {}).get('clientCredentials'):
                    flow = sec['flows']['clientCredentials']
                    token_url = flow.get('tokenUrl')
                    if not token_url:
                        auth_errors.append(f"OAuth2 ({name}): Missing 'tokenUrl' in clientCredentials flow.")
                        all_reqs_met_in_set = False; break

                    # Ensure token_url is absolute
                    if not urlparse(token_url).scheme:
                        base_url = get_base_url(spec, api_name) # Use correct base url
                        token_url = urljoin(base_url + '/', token_url.lstrip('/')) # Ensure base has trailing slash

                    client_id_env = f'OAUTH_{name.upper()}_CLIENT_ID'
                    client_secret_env = f'OAUTH_{name.upper()}_CLIENT_SECRET'
                    client_id = get_env_or_secret(client_id_env)
                    client_secret = get_env_or_secret(client_secret_env)

                    if not client_id or not client_secret:
                        auth_errors.append(f"OAuth2 ({name}): Missing '{client_id_env}' or '{client_secret_env}' in environment/secrets.")
                        all_reqs_met_in_set = False; break

                    data = {'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': client_secret}
                    # Add scopes if defined in flow AND required by this specific security requirement
                    required_scopes = security_reqs.get(name) # List of scopes for this req
                    if required_scopes and isinstance(required_scopes, list):
                         # Check if flow defines scopes - Optional according to spec
                         available_scopes = flow.get('scopes', {})
                         valid_scopes = [s for s in required_scopes if s in available_scopes]
                         if valid_scopes:
                              data['scope'] = ' '.join(valid_scopes)
                         # Warn if required scopes are not defined in the flow? Optional.
                         # else: auth_errors.append(f"OAuth2 ({name}): Required scopes {required_scopes} not defined in flow's scopes.")

                    resp = requests.post(token_url, data=data, timeout=REQUEST_TIMEOUT_SECONDS)
                    resp.raise_for_status()
                    token_data = resp.json()
                    access_token = token_data.get('access_token')

                    if access_token:
                        token_type = token_data.get('token_type', 'Bearer').capitalize()
                        current_req_headers['Authorization'] = f"{token_type} {access_token}"
                        st.sidebar.success(f"✅ OAuth2 Token ({name}) obtained.")
                        auth_successful_for_scheme = True
                    else:
                        auth_errors.append(f"OAuth2 ({name}): 'access_token' not found in response from {token_url}.")
                        all_reqs_met_in_set = False; break

                # --- API Key ---
                elif sec.get('type') == 'apiKey':
                    key_env = f'APIKEY_{name.upper()}'
                    key = get_env_or_secret(key_env)
                    if not key:
                        auth_errors.append(f"API Key ({name}): Missing '{key_env}' in environment/secrets.")
                        all_reqs_met_in_set = False; break

                    key_location = sec.get('in')
                    header_name = sec.get('name')
                    if key_location == 'header' and header_name:
                        current_req_headers[header_name] = key
                        st.sidebar.success(f"✅ API Key ({name}) configured for header '{header_name}'.")
                        auth_successful_for_scheme = True
                    elif key_location == 'query' and header_name:
                        # Query API keys handled during request building, just verify existence here
                        st.sidebar.success(f"✅ API Key ({name}) found for query param '{header_name}'.")
                        auth_successful_for_scheme = True # Mark as successful for requirement check
                    else:
                        auth_errors.append(f"API Key ({name}): Invalid or missing 'in' ('{key_location}') or 'name' ('{header_name}') field.")
                        all_reqs_met_in_set = False; break

                # --- HTTP Basic or Bearer ---
                elif sec.get('type') == 'http':
                    http_scheme = sec.get('scheme', '').lower()
                    if http_scheme == 'basic':
                        user_env = f'HTTP_{name.upper()}_USER'
                        pass_env = f'HTTP_{name.upper()}_PASS'
                        user = get_env_or_secret(user_env)
                        password = get_env_or_secret(pass_env) # Allows empty password if secret is set to ""
                        if user is None or password is None:
                            auth_errors.append(f"HTTP Basic ({name}): Missing '{user_env}' or '{pass_env}' in environment/secrets.")
                            all_reqs_met_in_set = False; break
                        auth_str = f"{user}:{password}"
                        encoded_auth = base64.b64encode(auth_str.encode()).decode()
                        current_req_headers['Authorization'] = f"Basic {encoded_auth}"
                        st.sidebar.success(f"✅ HTTP Basic Auth ({name}) configured.")
                        auth_successful_for_scheme = True
                    elif http_scheme == 'bearer':
                        token_env = f'HTTP_{name.upper()}_TOKEN' # Env var for pre-provided bearer token
                        token = get_env_or_secret(token_env)
                        if not token:
                            auth_errors.append(f"HTTP Bearer ({name}): Missing '{token_env}' in environment/secrets.")
                            all_reqs_met_in_set = False; break
                        current_req_headers['Authorization'] = f"Bearer {token}"
                        st.sidebar.success(f"✅ HTTP Bearer Token ({name}) configured.")
                        auth_successful_for_scheme = True
                    else:
                        auth_errors.append(f"HTTP Auth ({name}): Unsupported scheme '{sec.get('scheme', 'N/A')}'. Only 'basic' and 'bearer' are supported.")
                        all_reqs_met_in_set = False; break

                # --- Other Auth Types (Not Implemented) ---
                else:
                     auth_errors.append(f"Auth Type ({name}): Unsupported type '{sec.get('type', 'N/A')}'.")
                     all_reqs_met_in_set = False; break

            except requests.exceptions.RequestException as e:
                auth_errors.append(f"Auth Connection Error ({name}, type={sec.get('type')}): Failed. Details: {e}")
                all_reqs_met_in_set = False; break
            except Exception as e:
                auth_errors.append(f"Auth Setup Error ({name}, type={sec.get('type')}): {type(e).__name__} - {e}")
                all_reqs_met_in_set = False; break

            # If any scheme within the AND requirement set fails, stop processing this set
            if not auth_successful_for_scheme:
                 all_reqs_met_in_set = False
                 break # Break from inner loop (schemes within the set)

        # If all schemes in this requirement set were successfully configured, adopt the headers and stop
        if all_reqs_met_in_set and schemes_to_try_in_req: # Check if the req set wasn't effectively empty
            headers.update(current_req_headers) # Merge headers from this set
            obtained_auth = True
            st.sidebar.info(f"Auth successfully configured using requirement set: {', '.join(schemes_to_try_in_req)}")
            break # Break from outer loop (different OR requirement sets)

    # Final status reporting based on whether auth was obtained and if errors occurred
    unique_auth_errors = sorted(list(set(auth_errors)))
    if not obtained_auth and unique_auth_errors and spec.get('components', {}).get('securitySchemes'):
         st.sidebar.warning(f"⚠️ Could not automatically configure auth for '{api_name}' using any defined security requirement.")
         # Optionally display errors here or return them for display in the main app
         # for error in unique_auth_errors: st.sidebar.caption(f"- {error}")

    return headers, unique_auth_errors