import streamlit as st
import os
import json
import re
from collections import deque
from urllib.parse import urljoin
import time # For potential delays if needed
from dotenv import load_dotenv
# Import functions from our modules
from config import MAX_HISTORY, GEMINI_API_KEY # Only import necessary config
from utils import format_log_dict, mask_secret, build_proper_api_url
from openapi_utils import load_openapi_spec, get_base_url
from auth import get_auth_headers
from gemini_agent import find_matching_endpoint_gemini # Import core function
from coordination import coordinator_pattern, mesh_pattern, service_discovery_pattern
from api_request import build_request_details, execute_api_call, build_curl_command
from ui_components import (
    show_api_as_agent_concept, show_feedback_form, endpoint_table, auto_body_form
)
load_dotenv()
# --- Streamlit Page Configuration ---
st.set_page_config(page_title="API-as-Agent (5*A)", page_icon="🧑‍💻", layout="wide")

# --- Initialize Session State ---
def init_session_state():
    """Initializes session state variables if they don't exist."""
    defaults = {
        'history': deque(maxlen=MAX_HISTORY),
        'apis': {}, # Stores { 'api_name': spec_dict }
        'active_api_name': None,
        'coordination_pattern': 'coordinator', # Default pattern
        'last_gemini_raw_response': None,
        'api_auth_headers': {}, # Cache auth headers {api_name: headers}
        'api_auth_errors': {}, # Cache auth errors {api_name: [errors]}
        # Add state for the request form submission if needed
        'api_call_result': None,
        'api_call_error': None,
        'api_call_request_log': None,
        'api_call_response_log': None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# --- Sidebar ---
with st.sidebar:
    st.title("🧠 5*A Agent Settings")

    # --- API Management Section ---
    st.subheader("API Specs")
    uploaded_files = st.file_uploader(
        'Upload OpenAPI 3.0 spec(s) (YAML or JSON)',
        type=['yaml', 'yml', 'json'],
        accept_multiple_files=True
    )

    # Process uploads
    if uploaded_files:
        loaded_now_names = []
        for uploaded_file in uploaded_files:
            api_name_suggestion = os.path.splitext(uploaded_file.name)[0]
            if api_name_suggestion in st.session_state['apis']:
                st.warning(f"Reloading API spec for '{api_name_suggestion}'.")
            else:
                 st.info(f"Loading new API spec: '{api_name_suggestion}'")

            with st.spinner(f"Loading & Validating '{uploaded_file.name}'..."):
                spec, err = load_openapi_spec(uploaded_file)
                if err:
                    st.error(f"Error loading '{uploaded_file.name}': {err}")
                elif spec:
                    st.session_state['apis'][api_name_suggestion] = spec
                    loaded_now_names.append(api_name_suggestion)
                    # Clear cached auth for this API on reload/load
                    st.session_state['api_auth_headers'].pop(api_name_suggestion, None)
                    st.session_state['api_auth_errors'].pop(api_name_suggestion, None)
                    # Clear specific cached functions related to this API spec if needed
                    # e.g. @st.cache_data functions that depend on the spec content
                    # This might require more granular cache clearing if performance is critical
                else:
                    # Error handled by load_openapi_spec
                    pass

        if loaded_now_names:
            st.success(f"Loaded/Reloaded APIs: {', '.join(loaded_now_names)}")
            available_api_names = list(st.session_state['apis'].keys())
            # Set first loaded API as active if none is active or current active was removed/renamed
            if available_api_names and (st.session_state.get('active_api_name') is None or st.session_state.get('active_api_name') not in available_api_names):
                st.session_state['active_api_name'] = available_api_names[0]
                st.rerun() # Rerun to update UI reflecting new active API

    # API Selection Dropdown
    available_api_names = sorted(list(st.session_state.get('apis', {}).keys()))
    if available_api_names:
        # Ensure active_api_name is valid, default to first if not
        if st.session_state.get('active_api_name') not in available_api_names:
            st.session_state['active_api_name'] = available_api_names[0] if available_api_names else None

        try:
             current_index = available_api_names.index(st.session_state['active_api_name']) if st.session_state['active_api_name'] else 0
        except ValueError:
             current_index = 0 # Default to first if name somehow invalid
             st.session_state['active_api_name'] = available_api_names[0] if available_api_names else None

        selected_api_name = st.selectbox(
            "Active API (for single mode or Mesh primary)",
            options=available_api_names,
            index=current_index,
            key='active_api_selector'
        )
        # Update state only if selection changes to avoid unnecessary reruns/auth checks
        if selected_api_name != st.session_state.get('active_api_name'):
             st.session_state['active_api_name'] = selected_api_name
             # Clear previous API call results when switching API
             st.session_state['api_call_result'] = None
             st.session_state['api_call_error'] = None
             st.rerun()

    else:
        st.session_state['active_api_name'] = None
        st.caption("Upload an OpenAPI spec to begin.")


    # --- Coordination Pattern Selection ---
    if len(st.session_state.get('apis', {})) > 1:
        st.subheader("Coordination (Multi-API)")
        coord_options = ["coordinator", "mesh", "service_discovery"]
        coord_labels = {
            "coordinator": "Coordinator (Central Control)",
            "mesh": "Mesh (Primary + Peers)",
            "service_discovery": "Service Discovery (Directory)"
        }
        # Ensure current pattern is valid, default if not
        if st.session_state.get('coordination_pattern') not in coord_options:
            st.session_state['coordination_pattern'] = 'coordinator'

        st.session_state['coordination_pattern'] = st.radio(
            "Agent Coordination Pattern",
            options=coord_options,
            format_func=lambda x: coord_labels.get(x, x.capitalize()),
            index=coord_options.index(st.session_state['coordination_pattern']),
            key='coord_pattern_selector',
            help="How multiple API agents interact when >1 API is loaded."
        )
    else:
        # Default to single mode display if only one/zero API
        st.session_state['coordination_pattern'] = 'single'
        if available_api_names:
             st.caption("Coordination patterns enabled when >1 API is loaded.")


    # --- Authentication Status Section ---
    st.subheader("Authentication")
    active_api_name_for_auth = st.session_state.get('active_api_name')
    active_spec_for_auth = st.session_state.get('apis', {}).get(active_api_name_for_auth)

    if active_spec_for_auth and active_api_name_for_auth:
        # Use cached auth info if available
        auth_headers = st.session_state['api_auth_headers'].get(active_api_name_for_auth)
        auth_errors = st.session_state['api_auth_errors'].get(active_api_name_for_auth)

        # If not cached, compute and store
        if auth_headers is None or auth_errors is None:
             with st.spinner(f"Checking auth for '{active_api_name_for_auth}'..."):
                 auth_headers, auth_errors = get_auth_headers(active_spec_for_auth, active_api_name_for_auth)
                 st.session_state['api_auth_headers'][active_api_name_for_auth] = auth_headers
                 st.session_state['api_auth_errors'][active_api_name_for_auth] = auth_errors
                 # Rerun needed to display the newly fetched status correctly if it wasn't cached
                 # This might cause a flicker, consider optimizing if problematic
                 # st.rerun() # Let's avoid immediate rerun here, display what we have.

        # Display Auth Status
        with st.expander(f"Auth Status for '{active_api_name_for_auth}'", expanded=False):
             if auth_headers:
                 st.json({k: mask_secret(k, v) for k, v in auth_headers.items()})
             elif not auth_errors and not active_spec_for_auth.get('components', {}).get('securitySchemes'):
                  st.info("No security schemes defined. Assuming no auth needed.")
             elif not auth_headers and not auth_errors:
                  # This case might indicate a scheme exists but doesn't generate headers (e.g., query API key)
                  st.info("Auth scheme found (e.g., API Key in query), but no headers needed/generated by default.")

             if auth_errors:
                 st.warning("Auth configuration issues:")
                 for error in auth_errors: st.caption(f"- {error}")
    else:
         st.caption("Upload and select an API to see auth status.")


    # --- History / Logs Section ---
    st.subheader("Interaction History")
    log_container = st.container(height=300) # Scrollable history
    with log_container:
        history_list = list(st.session_state.get('history', [])) # Get a copy
        if history_list:
            for i, h in enumerate(history_list): # Iterate without modifying deque directly
                req = h.get('request', {})
                resp = h.get('response', {})
                status_code = resp.get('status', '?')
                is_success = isinstance(status_code, int) and 200 <= status_code < 300
                outcome_icon = "✅" if is_success else ("⏳" if status_code == '?' else "❌") # Add pending/unknown state?
                outcome_text = f"{status_code}" if isinstance(status_code, int) else resp.get('body', 'Error')[:20] if isinstance(resp.get('body'), str) else "Error"

                expander_title = f"{i+1}. {req.get('method','?')} {req.get('path','?')} ({req.get('api','?')}) -> {outcome_icon} {outcome_text}"
                with st.expander(expander_title):
                    st.caption(f"Query: '{h.get('natural_language', 'N/A')}'")
                    st.caption("Request:")
                    # format_log_dict used before adding to history, so display directly
                    st.json(req, expanded=False)
                    st.caption("Response:")
                    st.json(resp, expanded=False)
        else:
            st.caption("No interactions yet.")

    # --- Raw Gemini Response Log ---
    st.subheader("Last Agent Raw Output")
    with st.expander("Show/Hide Raw Output", expanded=False):
        st.text_area("Raw Agent Output", value=st.session_state.get('last_gemini_raw_response', "N/A"), height=200, disabled=True, key="gemini_raw_output_area")


# ======================================
# --- Main Content Area ---
# ======================================
st.title("🧑‍💻 API-as-Agent (5*A) Demo")

# Explanation Expander
with st.expander("What is API-as-an-AI-Agent (5*A)? Click to learn more...", expanded=False):
    show_api_as_agent_concept()

# Check if APIs are loaded
if not st.session_state.get('apis'):
    st.warning("👈 Please upload at least one OpenAPI spec using the sidebar to begin.")
    st.stop()

# Get active API details safely
active_api_name = st.session_state.get('active_api_name')
active_spec = st.session_state.get('apis', {}).get(active_api_name) if active_api_name else None

if not active_api_name or not active_spec:
     st.error("No active API selected or loaded. Please check the sidebar.")
     st.stop()

# Display Header for Active API and Mode
api_title = active_spec.get('info', {}).get('title', active_api_name)
num_apis = len(st.session_state.get('apis', {}))
mode_display = f"Coordination: `{st.session_state['coordination_pattern']}`" if num_apis > 1 else "Mode: `Single API`"
st.header(f"Interact with: {api_title}")
st.caption(f"Active API: `{active_api_name}` | {mode_display}")


# --- Endpoint Discovery / Browse ---
tags = sorted({tag for p in active_spec.get('paths', {}).values() if isinstance(p, dict) for m in p.values() if isinstance(m, dict) for tag in m.get('tags', [])})
with st.expander(f"Browse Endpoints for '{active_api_name}'", expanded=False):
    col1, col2 = st.columns([2,1])
    with col1:
        tag_filter = st.selectbox(f'Filter by tag ({len(tags)} available)', ['All'] + tags, key=f'tag_filter_{active_api_name}')
    with col2:
        endpoint_limit = st.slider('Max endpoints to display', 10, 200, 50, key=f'limit_{active_api_name}')

    endpoint_df_data = endpoint_table(active_spec, tag_filter if tag_filter != 'All' else None, limit=endpoint_limit)
    st.dataframe(endpoint_df_data, use_container_width=True, hide_index=True, height=min(300, (len(endpoint_df_data)+1)*35+3)) # Dynamic height


# --- Natural Language Input ---
st.subheader("💬 Ask the API Agent")
user_input = st.text_input(
    'Enter request in natural language (e.g., "List first 10 users", "What can you do?")',
    key='user_query_input',
    placeholder="Type your request here..."
)

col_a, col_b = st.columns([3,1])
with col_a:
    max_endpoints_gemini = st.slider(
        'Max endpoints for Agent context', 10, 200, 75,
        key='gemini_max_endpoints',
        help="Limits endpoint summaries sent to the Agent (affects context window/cost)."
        )
with col_b:
    run_button = st.button("▶️ Send to Agent", use_container_width=True, key="send_agent_button")


# --- Agent Processing Logic ---
# This section runs when the button is clicked and input is provided
if run_button and user_input:
    # Clear previous API call state before new agent run
    st.session_state['api_call_result'] = None
    st.session_state['api_call_error'] = None
    st.session_state['api_call_request_log'] = None
    st.session_state['api_call_response_log'] = None

    agent_response_area = st.container(border=True)
    with agent_response_area:
        st.markdown("#### 🤖 Agent Response")
        with st.spinner('Agent is thinking... Processing your request...'):
            context = list(st.session_state['history']) # Get current history
            api_name_to_use = active_api_name
            spec_to_use = active_spec
            auth_headers_to_use = st.session_state.get('api_auth_headers', {}).get(api_name_to_use, {})
            intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response = (None,) * 9

            # --- Apply Coordination Pattern ---
            pattern = st.session_state['coordination_pattern']
            all_apis = st.session_state['apis']

            start_time = time.time() # Start timer

            if pattern == 'coordinator' and num_apis > 1:
                api_name_to_use, intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response = coordinator_pattern(
                    all_apis, user_input, context, max_endpoints_gemini
                )
            elif pattern == 'mesh' and num_apis > 1:
                api_name_to_use, intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response = mesh_pattern(
                    all_apis, user_input, context, max_endpoints_gemini, active_api_name # Pass primary API
                )
            elif pattern == 'service_discovery' and num_apis > 1:
                api_name_to_use, intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response = service_discovery_pattern(
                    all_apis, user_input, context, max_endpoints_gemini
                )
            else: # Single API mode or fallback
                api_name_to_use = active_api_name # Explicitly set for single mode
                spec_to_use = active_spec
                intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response = find_matching_endpoint_gemini(
                    spec_to_use, user_input, api_name_to_use, context, max_endpoints_gemini
                )

            end_time = time.time() # End timer
            processing_time = end_time - start_time

            # Store the raw response from the agent/coordinator function
            st.session_state['last_gemini_raw_response'] = raw_response

            # --- Process Agent's Decision ---
            st.caption(f"Agent processing time: {processing_time:.2f} seconds")

            if not api_name_to_use or intent == 'unknown' or (intent=='endpoint_call' and not path):
                st.error(f"😥 Agent could not confidently handle the request.")
                if reasoning:
                    st.warning(f"**Agent Reasoning:** {reasoning}")
                st.stop() # Stop processing this run

            # Update spec and auth if a different API was selected by coordination
            if api_name_to_use != active_api_name:
                st.info(f"🔄 Coordination pattern selected API: **{api_name_to_use}**")
                spec_to_use = all_apis.get(api_name_to_use)
                if not spec_to_use:
                     st.error(f"Error: Selected API '{api_name_to_use}' spec not found.")
                     st.stop()
                # Get auth for the *selected* API (use cache if possible)
                auth_headers_to_use = st.session_state['api_auth_headers'].get(api_name_to_use)
                if auth_headers_to_use is None:
                     st.warning(f"Auth headers not cached for selected API '{api_name_to_use}', attempting fetch...")
                     auth_headers_to_use, _ = get_auth_headers(spec_to_use, api_name_to_use)
                     st.session_state['api_auth_headers'][api_name_to_use] = auth_headers_to_use # Cache it
                # We assume auth_errors are less critical here, focusing on headers

            # --- Handle Discovery Intent ---
            if intent == 'discovery':
                st.subheader("🧭 API Capabilities Summary")
                st.markdown(discovery_resp if discovery_resp else "The agent indicated this is a discovery request but provided no summary.")
                if reasoning:
                    with st.expander("Agent Reasoning", expanded=False): st.info(reasoning)
                # Store discovery interaction in history? Optional.
                # discovery_log = {'request': {'natural_language': user_input, 'api': api_name_to_use, 'intent': 'discovery'}, 'response': {'status': 'N/A', 'body': discovery_resp}}
                # st.session_state['history'].appendleft(format_log_dict(discovery_log))
                st.stop() # Stop processing, discovery fulfilled

            # --- Handle Endpoint Call Intent ---
            st.success(f"✅ Agent selected API Call:")
            st.markdown(f"**API:** `{api_name_to_use}` | **Endpoint:** `{method.upper()} {path}` | **Confidence:** `{confidence:.2f}`")
            if reasoning:
                with st.expander("Agent Reasoning", expanded=False): st.info(reasoning)

            # Display feedback form *before* the API call form
            show_feedback_form(api_name_to_use, path, method, user_input)

            # Store intermediate results needed for the form in session state
            st.session_state['selected_api_name'] = api_name_to_use
            st.session_state['selected_spec'] = spec_to_use
            st.session_state['selected_path'] = path
            st.session_state['selected_method'] = method
            st.session_state['selected_op_details'] = op_details
            st.session_state['gemini_hints'] = gemini_hints
            st.session_state['auth_headers_for_call'] = auth_headers_to_use


# --- API Call Form Area ---
# This part renders if the agent selected an endpoint_call in the *previous* run
if st.session_state.get('selected_api_name') and st.session_state.get('selected_method'):
    st.markdown("---")
    st.subheader("🛠️ Prepare & Execute API Call")

    # Retrieve details from session state
    api_name = st.session_state['selected_api_name']
    spec = st.session_state['selected_spec']
    path = st.session_state['selected_path']
    method = st.session_state['selected_method']
    op = st.session_state['selected_op_details']
    hints = st.session_state.get('gemini_hints', {})
    auth_headers = st.session_state.get('auth_headers_for_call', {})

    # Use a unique key for the form based on the selected endpoint + initial query hash
    form_key = f"api_call_form_{api_name}_{method}_{path}_{hash(user_input)}"

    # Variables to hold cURL command and final_url for use outside the form
    curl_command = None
    final_url = None
    url_error = None
    body_data_input = None
    final_query_params = None
    final_headers = None
    final_content_type = None

    with st.form(key=form_key):
        manual_param_values = {} # For non-body parameters
        body_data_input = None   # For request body

        # Build initial request details based on spec and Gemini hints
        query_params_spec, headers_spec, path_params_spec, body_schema, body_content_type = build_request_details(
            op, path, method, hints, spec, auth_headers, api_name
            )

        st.markdown("**Parameters & Request Body**")
        st.caption("Review and modify values extracted by the agent or defined in the spec.")

        # --- Parameter Inputs (Path, Query, Header) ---
        param_container = st.container()
        with param_container:
            param_defs = op.get('parameters', []) if isinstance(op, dict) else []
            if param_defs:
                param_cols = st.columns(2)
                col_idx = 0
                param_order = {'path': 0, 'query': 1, 'header': 2, 'cookie': 3}
                sorted_params = sorted(param_defs, key=lambda p: (param_order.get(p.get('in'), 99), p.get('name', 'zzzz')))

                for param in sorted_params:
                    if not isinstance(param, dict): continue
                    pname = param.get('name')
                    ploc = param.get('in')
                    if not pname or not ploc: continue

                    ptype = param.get('schema', {}).get('type', 'string')
                    preq = param.get('required', False)
                    pdesc = param.get('description', '')
                    label = f"{pname} ({ploc}){' *' if preq else ''}"
                    help_txt = f"Type: {ptype}. {pdesc}".strip()
                    # Use value from hints if available, falling back to schema default
                    default_val = hints.get(pname, param.get('schema', {}).get('default'))
                    # Convert default_val to string for text inputs, handle None for number inputs
                    str_default = str(default_val) if default_val is not None else ""

                    widget_key = f"{form_key}_param_{pname}" # Unique key within form
                    input_value = None

                    # Render input based on location
                    target_col = param_cols[col_idx % 2]
                    if ploc in ['query', 'path']:
                        with target_col:
                            if ptype == 'boolean':
                                bool_default = False # Default to False if not clearly true
                                if isinstance(default_val, bool): bool_default = default_val
                                elif isinstance(default_val, (str, int)): bool_default = str(default_val).lower() in ['true', '1', 'yes']
                                input_value = st.checkbox(label, value=bool_default, help=help_txt, key=widget_key)
                            elif ptype == 'integer':
                                int_default = None
                                try: int_default = int(default_val) if default_val is not None else None
                                except (ValueError, TypeError): pass
                                input_value = st.number_input(label, value=int_default, step=1, format="%d", help=help_txt, key=widget_key)
                            elif ptype == 'number':
                                float_default = None
                                try: float_default = float(default_val) if default_val is not None else None
                                except (ValueError, TypeError): pass
                                input_value = st.number_input(label, value=float_default, format="%.5f", help=help_txt, key=widget_key)
                            else: # Default string
                                input_value = st.text_input(label, value=str_default, help=help_txt, key=widget_key)

                            # Store value if not None (st.number_input returns None if empty)
                            if input_value is not None:
                                manual_param_values[pname] = input_value
                        col_idx += 1
                    elif ploc == 'header':
                        # Display header param info but don't make it easily editable if derived from auth/spec
                        # Check if this header might be set by auth already
                        is_auth_header = pname in auth_headers or any(pname.lower() == h.lower() for h in auth_headers)
                        with target_col:
                             # Use header value from spec build if available, else hint/default
                             current_header_val = headers_spec.get(pname, str_default)
                             st.text_input(label, value=current_header_val, help=help_txt, key=widget_key, disabled=is_auth_header)
                             # Store non-disabled header values if user might change them (though currently disabled if auth sets it)
                             if not is_auth_header:
                                  manual_param_values[pname] = current_header_val # Store initial value, user can't edit if disabled
                        col_idx += 1

            else:
                st.caption("No parameters (query, path, header) defined in spec for this endpoint.")


        # --- Request Body Input ---
        body_container = st.container()
        with body_container:
            if body_schema:
                st.markdown(f"**Request Body (`{body_content_type or 'N/A'}`)**")
                # Pass Gemini's body hints (part of combined 'hints') as defaults
                body_data_input = auto_body_form(body_schema, current_vals=hints, form_key_prefix=form_key)
            else:
                st.caption("No request body defined for this endpoint.")


        # --- Final Request Details & Submission ---
        st.divider()
        final_query_params, final_headers, final_path_params, _, final_content_type = build_request_details(
            op, path, method, manual_param_values, spec, auth_headers, api_name
            )
        base_url = get_base_url(spec, api_name)
        st.markdown(f"**Base URL:** `{base_url}`")  # Show the base URL for clarity
        # Substitute path parameters into the URL template
        url_path_filled = path
        missing_path_params = []
        path_param_names_in_spec = {p['name'] for p in op.get('parameters', []) if isinstance(p, dict) and p.get('in') == 'path'}

        for pname in path_param_names_in_spec:
            placeholder = f"{{{pname}}}"
            if placeholder in url_path_filled:
                # Use value from manual_param_values if provided, else None
                pval = manual_param_values.get(pname)
                if pval is not None:
                    url_path_filled = url_path_filled.replace(placeholder, str(pval))
                else:
                    missing_path_params.append(pname) # Parameter needed but not provided

        # Check again if any placeholders remain after substitution
        if "{" in url_path_filled and "}" in url_path_filled:
            # Add any remaining placeholders found via regex just in case
            remaining = re.findall(r"\{(.*?)\}", url_path_filled)
            missing_path_params.extend(r for r in remaining if r not in missing_path_params)

        final_url = None
        url_error = None
        if missing_path_params:
            url_error = f"Missing required path parameter(s): {', '.join(sorted(list(set(missing_path_params))))}."
        else:
            try:
                # Get base URL ensuring it has a proper scheme
                base_url = get_base_url(spec, api_name)
                
                # Use our special URL construction function that properly handles API version paths
                final_url = build_proper_api_url(base_url, url_path_filled)
                
                
                # Extra validation
                if not final_url or not (final_url.startswith('http://') or final_url.startswith('https://')):
                    url_error = f"Final URL '{final_url}' does not have a valid scheme (http:// or https://)"
            except ValueError as e:
                url_error = f"Could not construct final URL: {e}. Base: '{base_url}', Path: '{url_path_filled}'"


        # --- Confirmation Expander ---
        with st.expander("Confirm Request Details", expanded=True):
            if final_url:
                st.markdown(f"**URL:** `{final_url}`")  # Show the full URL with base
            else:
                st.markdown(f"**URL:** `<Error: {url_error}>`")
            st.markdown(f"**Method:** `{method.upper()}`")
            st.markdown("**Headers:**")
            st.json({k: mask_secret(k,v) for k,v in final_headers.items()}, expanded=False)
            if final_query_params:
                st.markdown("**Query Parameters:**")
                st.json(final_query_params, expanded=False)
            if body_data_input:
                st.markdown(f"**Request Body ({final_content_type or 'N/A'}):**")
                st.json(body_data_input, expanded=False)
            elif body_schema:
                st.caption("Request Body is defined but currently empty.")

        # --- Form Submit Button ---
        submitted = st.form_submit_button(
            "🚀 Send API Request",
            disabled=(final_url is None), # Disable if URL is invalid
            use_container_width=True  # Make button full width for visibility
        )

        if submitted and final_url:
            st.session_state['api_call_submitted'] = True
            st.session_state['api_call_method'] = method
            st.session_state['api_call_url'] = final_url
            st.session_state['api_call_headers'] = final_headers
            st.session_state['api_call_query_params'] = final_query_params
            st.session_state['api_call_body_data'] = body_data_input
            st.session_state['api_call_content_type'] = final_content_type
            st.session_state['api_call_api_name'] = api_name # Log which API was called
            st.session_state['api_call_path'] = path # Log original path template

            # Clear intermediate state after capturing form data
            st.session_state['selected_api_name'] = None
            st.session_state['selected_spec'] = None
            st.session_state['selected_path'] = None
            st.session_state['selected_method'] = None
            st.session_state['selected_op_details'] = None
            st.session_state['gemini_hints'] = None
            st.session_state['auth_headers_for_call'] = None
            st.rerun() # Rerun to process the submission outside the form

    # Show the download button outside the form, only if final_url is valid
    if final_url:
        curl_command = build_curl_command(method, final_url, final_headers, final_query_params, body_data_input, final_content_type)
        st.download_button(label='Download as cURL', data=curl_command, file_name=f'{api_name}_{method}.sh', mime='text/x-shellscript')
    elif url_error:
        st.caption("cURL command cannot be generated due to URL error.")


# --- API Call Execution and Response Display ---
# This block runs AFTER the form is submitted (due to the rerun)
if st.session_state.get('api_call_submitted'):
    st.subheader("📡 API Response")
    with st.spinner('Sending request to API...'):
        # Retrieve call details from session state
        method = st.session_state['api_call_method']
        url = st.session_state['api_call_url']
        headers = st.session_state['api_call_headers']
        query_params = st.session_state['api_call_query_params']
        body_data = st.session_state['api_call_body_data']
        content_type = st.session_state['api_call_content_type']
        api_name = st.session_state['api_call_api_name']
        path = st.session_state['api_call_path']

        # Prepare logs
        request_log = {
            'natural_language': user_input, # Need to ensure user_input is available here, maybe store it too? Yes, store it.
            'api': api_name,
            'method': method.upper(),
            'url': url,
            'path': path, # Original path template
            'headers': headers, # Raw headers before masking for logging
            'params': query_params,
            'body': body_data
        }
        st.session_state['api_call_request_log'] = request_log # Store for history

        response_log = {}
        api_response, error = execute_api_call(method, url, headers, query_params, body_data, content_type)

        if error:
            st.error(f"API Request Failed: {error}")
            response_log = {'status': 'Error', 'body': error}
        elif api_response is not None:
            st.write(f"Status Code: `{api_response.status_code}`")
            response_log['status'] = api_response.status_code
            # Log raw headers before masking
            response_log['headers'] = dict(api_response.headers)

            # Try to parse JSON, otherwise show text
            try:
                resp_json = api_response.json()
                st.json(resp_json)
                response_log['body'] = resp_json
            except json.JSONDecodeError:
                resp_text = api_response.text
                # Limit display height for long text responses
                display_height = min(max(100, len(resp_text)//2 if resp_text else 100), 400)
                st.text_area("Response Body (non-JSON)", resp_text, height=display_height , disabled=True)
                response_log['body'] = resp_text[:5000] # Store truncated text log
        else:
            # Should not happen if error is None, but as fallback
            st.error("API call did not return a response or an error.")
            response_log = {'status': 'Error', 'body': 'No response object received.'}

        st.session_state['api_call_response_log'] = response_log

        # Add to history
        st.session_state['history'].appendleft({
            'request': format_log_dict(request_log), # Mask sensitive info before storing
            'response': format_log_dict(response_log),# Mask sensitive info before storing
            'natural_language': user_input # Store the original query with the history entry
        })

    # Clear submission flag and details after processing
    st.session_state['api_call_submitted'] = False
    # Keep request/response logs available? Maybe clear them too unless needed elsewhere.
    # Let's clear them to prevent re-display on next action unless explicitly needed.
    # st.session_state['api_call_request_log'] = None
    # st.session_state['api_call_response_log'] = None
    # We don't rerun here, let the user see the response.