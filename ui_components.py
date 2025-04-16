import streamlit as st
import json

# --- UI Component Functions ---

def show_api_as_agent_concept():
    """Displays the explanation of the API-as-an-AI-Agent concept."""
    # Content copied directly from original file
    st.markdown("""
## API-as-an-AI-Agent (5*A): Now Smarter with Coordination

_Ever wish you could just talk to an API instead of reading pages of docs and debugging schema mismatches? I did too. That’s why I built a tool that converts API specs into full-blown AI agents — or as I like to call it, **API-as-an-AI-Agent** (aka **5\*A**)._

### What I Built

At its core, this tool wraps any OpenAPI (or similar spec) into a natural-language-friendly agent. You ask questions like:  
> _“What’s the weather in London next week?”_  
And the agent figures out which endpoint to hit and how to structure the call — all without needing to crack open the docs.

It’s like giving APIs a personality — a human-friendly, language-savvy persona.

### Inspired by MCP Servers

Now here's where it gets more interesting.

Recently, I re-architected the coordination layer using ideas inspired by **Model Context Protocol (MCP)** servers — systems designed to let AI agents communicate, route context, and coordinate actions. While my tool isn’t built *on* MCP, it’s very much **analogous** in spirit.

With these MCP-like patterns in place, 5\*A agents can now:
- Collaborate to fulfill complex requests
- Route queries dynamically between APIs
- Handle ambiguity with context awareness

In short, coordination just got **smarter and more flexible**.

### How It Works (Briefly)

- APIs are turned into self-contained agents that understand their own capabilities.
- A central coordinator (or mesh, or discovery layer — your choice!) routes incoming user queries to the best agent.
- Agents generate and execute valid API calls from plain language — and return structured responses.

Think: conversational interface meets programmable API backend.

### Why This Matters

This isn’t just a UI trick. It’s a new way of thinking about API interaction — one where:
- **Dev onboarding is faster**
- **Integration is simpler**
- **Documentation becomes optional**

With MCP-style coordination, agents now feel less like tools and more like **collaborators**.

---

If you’ve ever imagined a future where APIs talk back, this is a small step toward that. And it’s open for anyone to build on.

Let me know what you think — or better yet, try it out.
        """)

def show_feedback_form(api_name, path, method, user_query):
    """UI for collecting user feedback on the agent's performance."""
    # Use a more specific key including the query to allow feedback on reruns
    feedback_key = f"feedback_{api_name}_{method}_{path}_{hash(user_query)}"

    # Initialize feedback state for this specific query if not present
    if feedback_key not in st.session_state:
        st.session_state[feedback_key] = {'submitted': False, 'correct': None}

    # Display based on submission status
    if st.session_state[feedback_key]['submitted']:
         feedback_status = "👍 Correct" if st.session_state[feedback_key]['correct'] else "👎 Incorrect"
         st.markdown(f"*Feedback submitted for this query/endpoint: {feedback_status}*")
    else:
        with st.container(border=True):
             st.write(f"For query: *'{user_query}'*, agent chose `{method.upper()} {path}` on API `{api_name}`.")
             st.write("**Was this the correct API call?** (Your feedback helps improve the agent!)")
             col1, col2, col3 = st.columns([1,1,3])
             with col1:
                 if st.button("👍 Yes", key=f"yes_{feedback_key}", help="Confirm this was the correct API and endpoint."):
                     st.session_state[feedback_key]['correct'] = True
                     st.session_state[feedback_key]['submitted'] = True
                     st.success("Thank you for your feedback!")
                     st.rerun()
             with col2:
                 if st.button("👎 No", key=f"no_{feedback_key}", help="Indicate this was NOT the correct API/endpoint."):
                     st.session_state[feedback_key]['correct'] = False
                     st.session_state[feedback_key]['submitted'] = True
                     st.warning("Thanks! This feedback helps improve the agent.")
                     st.rerun()


def endpoint_table(spec, tag=None, limit=50):
    """Generates a list of dicts for displaying endpoints in a table."""
    data = []
    count = 0
    if 'paths' not in spec or not isinstance(spec.get('paths'), dict): return data

    sorted_paths = sorted(spec.get('paths', {}).items())

    for path, methods in sorted_paths:
        if not isinstance(methods, dict): continue # Skip invalid path items

        method_order = {'get': 0, 'post': 1, 'put': 2, 'patch': 3, 'delete': 4}
        sorted_methods = sorted(methods.items(), key=lambda item: method_order.get(item[0].lower(), 99))

        for method, op in sorted_methods:
            if not isinstance(op, dict): continue # Skip non-operation objects

            op_tags = op.get('tags', [])
            if tag and tag not in op_tags: continue

            data.append({
                'Method': method.upper(),
                'Path': path,
                'Summary': op.get('summary', op.get('description', ''))[:100],
                'Tags': ', '.join(op_tags)
            })
            count += 1
            if count >= limit:
                st.warning(f"Displaying first {limit} endpoints matching filter. Refine filter or increase limit if needed.")
                return data
    return data

def auto_body_form(schema, prefix='', current_vals=None, form_key_prefix=""):
    """Recursively builds Streamlit form elements for a JSON body schema.

    Args:
        schema (dict): The JSON schema object (or sub-schema).
        prefix (str): String prefix for nested field labels.
        current_vals (dict): Dictionary of current/default values for this schema level.
        form_key_prefix (str): Unique prefix for Streamlit widget keys within the form.

    Returns:
        dict: A dictionary containing the values entered by the user for this schema level.
    """
    vals = {}
    if not isinstance(schema, dict):
        st.warning(f"Schema definition at prefix '{prefix}' is not a dictionary.")
        return {}

    required_fields = schema.get('required', [])

    # Handle 'allOf' by merging properties - simplified merge
    if 'allOf' in schema and isinstance(schema['allOf'], list):
        merged_properties = {}
        merged_required = list(required_fields)
        for sub_schema in schema['allOf']:
            if isinstance(sub_schema, dict):
                 merged_properties.update(sub_schema.get('properties', {}))
                 merged_required.extend(sub_schema.get('required', []))
        schema = {'properties': merged_properties, 'required': list(set(merged_required))}

    schema_properties = schema.get('properties', {})

    # Handle case where schema is object but has no properties (allow raw JSON input)
    if schema.get('type') == 'object' and not schema_properties:
        st.info(f"Schema at '{prefix}' allows arbitrary key-value pairs. Use the JSON input area below.")
        # Use st.json_editor if available, else text_area
        default_json = current_vals if isinstance(current_vals, dict) else {}
        json_key = f"{form_key_prefix}_json_editor_{prefix}"
        if hasattr(st, 'json_editor'):
            user_json = st.json_editor(default_json, key=json_key, height=200)
            return user_json # Returns dict directly
        else:
            json_text = st.text_area(f"JSON Object Body ({prefix}) *",
                                      value=json.dumps(default_json, indent=2),
                                      height=200, key=json_key,
                                      help="Enter the full JSON object here.")
            try:
                 return json.loads(json_text) if json_text else {}
            except json.JSONDecodeError:
                 st.error("Invalid JSON entered in text area.")
                 return {}

    # Generate form elements for defined properties
    sorted_properties = sorted(schema_properties.items())

    for k, v in sorted_properties:
        if not isinstance(v, dict): continue # Skip invalid property definitions

        key_label = f"{prefix}{k}"
        field_required = k in required_fields
        label = f"{key_label}{' *' if field_required else ''}"
        description = v.get('description', '')
        field_type = v.get('type','object') # Default to object
        default_val = current_vals.get(k) if isinstance(current_vals, dict) else v.get('default') # Use schema default if no current val
        help_text = f"Type: {field_type}. {description}".strip()
        widget_key = f"{form_key_prefix}_field_{key_label}" # Unique key for widget

        # Enum with selectbox
        if 'enum' in v and isinstance(v['enum'], list):
            enum_options = v['enum']
            try: # Handle default value not being in options gracefully
                default_index = enum_options.index(default_val) if default_val in enum_options else 0
            except ValueError:
                default_index = 0
            vals[k] = st.selectbox(label, options=enum_options, index=default_index, help=help_text, key=widget_key)

        # Nested object (recursive call)
        elif field_type == 'object':
            st.markdown(f"**{label}:**")
            vals[k] = auto_body_form(v, prefix=key_label+'.', current_vals=default_val, form_key_prefix=form_key_prefix)

        # Array (simple comma-separated input for now)
        elif field_type == 'array':
             st.markdown(f"**{label} (List):**")
             item_type = v.get('items', {}).get('type', 'string')
             array_help = help_text + f"\nEnter items (type: {item_type}) separated by commas."
             # Handle default array value
             default_str = ', '.join(map(str, default_val)) if isinstance(default_val, list) else ''
             arr_input = st.text_area(f"Items for {key_label}", value=default_str, help=array_help, key=widget_key)
             raw_list = [x.strip() for x in arr_input.split(',') if x.strip()] if arr_input else []
             converted_list = []
             try: # Attempt type conversion
                  for item in raw_list:
                       if item_type == 'integer': converted_list.append(int(item))
                       elif item_type == 'number': converted_list.append(float(item))
                       elif item_type == 'boolean': converted_list.append(item.lower() in ['true', '1', 'yes'])
                       else: converted_list.append(item) # Default string
                  vals[k] = converted_list
             except ValueError:
                  st.error(f"Invalid value entered for array '{key_label}'. Expected type '{item_type}'.")
                  vals[k] = [] # Default to empty list on error

        # Boolean
        elif field_type == 'boolean':
            # Ensure default_val is a boolean
            bool_default = False
            if isinstance(default_val, bool): bool_default = default_val
            elif isinstance(default_val, str): bool_default = default_val.lower() in ['true', '1', 'yes']
            vals[k] = st.checkbox(label, value=bool_default, help=help_text, key=widget_key)

        # Integer
        elif field_type == 'integer':
             int_default = None
             try: int_default = int(default_val) if default_val is not None else None
             except (ValueError, TypeError): pass
             vals[k] = st.number_input(label, value=int_default, step=1, format="%d", help=help_text, key=widget_key) # Use format %d

        # Number (Float)
        elif field_type == 'number':
             num_default = None
             try: num_default = float(default_val) if default_val is not None else None
             except (ValueError, TypeError): pass
             vals[k] = st.number_input(label, value=num_default, format="%.5f", help=help_text, key=widget_key)

        # String and others (use text_input, handle formats minimally)
        else:
            str_format = v.get('format')
            default_str_val = str(default_val) if default_val is not None else ""
            input_type = "password" if 'password' in str_format else "default"

            if str_format == 'byte': # Base64 encoded string
                 vals[k] = st.text_area(label, value=default_str_val, help=help_text + " (Base64 encoded)", key=widget_key)
            elif str_format in ['date', 'date-time']:
                 help_suffix = " (YYYY-MM-DD)" if str_format == 'date' else " (YYYY-MM-DDTHH:MM:SSZ)"
                 vals[k] = st.text_input(label, value=default_str_val, help=help_text + help_suffix, key=widget_key)
            else: # Regular string
                 vals[k] = st.text_input(label, value=default_str_val, help=help_text, key=widget_key, type=input_type)


    # Clean up result: Remove keys with None values unless explicitly required?
    # For simplicity, let's return all keys generated by the form for now.
    # The execute call might need to handle None values appropriately.
    # Let's implement a basic cleanup: remove None values, empty strings (unless required?), empty lists/dicts?
    cleaned_vals = {}
    for k, v in vals.items():
        is_required = k in required_fields
        include_field = False

        if isinstance(v, dict):
            # Recursively clean nested dictionary
            cleaned_v = {nk: nv for nk, nv in v.items() if nv is not None} # Basic clean: remove None
            if cleaned_v: # Include if object is not empty after cleaning
                include_field = True
                vals[k] = cleaned_v # Update vals with cleaned version
            elif is_required: # Include empty dict if required? OpenAPI spec might allow this.
                 include_field = True
                 vals[k] = {}
        elif isinstance(v, list):
            if v: # Include if list is not empty
                 include_field = True
            elif is_required: # Include empty list if required
                 include_field = True
        elif v is not None: # Include non-None primitives
             # Should we include empty strings ""? Generally yes, unless not required.
             if v != "" or is_required:
                  include_field = True
        # Handle boolean False explicitly (it's a valid value, not 'empty')
        if field_type == 'boolean' and v is False:
            include_field = True

        if include_field:
            cleaned_vals[k] = vals[k]

    return cleaned_vals