import streamlit as st
import google.generativeai as genai
import json
import re
from config import GEMINI_MODEL_NAME #, DEFAULT_SAFETY_SETTINGS
from utils import extract_json_from_response

# Store last raw response globally within this module or pass back if needed
last_gemini_raw_response = None

# Caching for Gemini responses - Keyed by prompt and API Key (implicitly via genai config)
@st.cache_data(show_spinner="🧠 Asking Gemini...", ttl=3600) # Cache for 1 hour
def call_gemini(prompt, model_name=GEMINI_MODEL_NAME):
    """Calls the Gemini API and returns the text response."""
    global last_gemini_raw_response
    try:
        model = genai.GenerativeModel(model_name)
        # To add safety settings:
        # response = model.generate_content(prompt, safety_settings=DEFAULT_SAFETY_SETTINGS)
        response = model.generate_content(prompt)
        last_gemini_raw_response = response.text # Store raw response text

        # Check if response was blocked
        if not response.parts:
             block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
             error_msg = f"Gemini API call blocked. Reason: {block_reason}"
             st.error(error_msg)
             print(f"Blocked Prompt:\n{prompt[:500]}...") # Log partial prompt
             # Return a structured error JSON consistent with expected format
             return json.dumps({
                 "intent": "unknown",
                 "confidence": 0.0,
                 "reasoning": error_msg,
                 "discovery_response": None,
                 "path": None, "method": None, "parameters": None, "requestBodyData": None
             })

        return response.text
    except Exception as e:
        error_msg = f"Gemini API call failed: {type(e).__name__} - {e}"
        st.error(error_msg)
        print(f"Failed Prompt:\n{prompt[:500]}...") # Log partial prompt
        last_gemini_raw_response = f"Error: {error_msg}" # Store error in raw response
        # Return structured error JSON
        return json.dumps({
            "intent": "unknown",
            "confidence": 0.0,
            "reasoning": error_msg,
            "discovery_response": None,
            "path": None, "method": None, "parameters": None, "requestBodyData": None
        })

@st.cache_data(show_spinner=False)
def summarize_spec_for_gemini(spec, max_endpoints=100):
    """Creates a concise summary of API endpoints for the Gemini prompt."""
    summary = []
    count = 0
    if 'paths' not in spec:
        return [] # Handle specs with no paths

    for path, methods in spec.get('paths', {}).items():
        for method, op in methods.items():
            if not isinstance(op, dict): continue # Skip non-operation entries
            if count >= max_endpoints: break

            params_summary = [{
                'name': p.get('name', '?'), 'in': p.get('in', '?'),
                'required': p.get('required', False),
                'type': p.get('schema', {}).get('type', 'string'),
                'description': p.get('description', '')[:75] # Shorten desc
            } for p in op.get('parameters', []) if isinstance(p, dict)]

            request_body_summary = None
            if isinstance(op.get('requestBody'), dict):
                 request_body_summary = "Required" if op['requestBody'].get('required', False) else "Optional"

            op_summary = {
                'path': path,
                'method': method.upper(),
                'summary': op.get('summary', op.get('description', ''))[:150], # Limit length
                'operationId': op.get('operationId'),
                'parameters': params_summary or None, # Use None if empty
                'requestBody': request_body_summary
            }
            # Only add description if summary is very short/missing
            # if not op_summary['summary'] or len(op_summary['summary']) < 30:
            #      op_summary['description'] = op.get('description', '')[:100]

            summary.append(op_summary)
            count += 1
        if count >= max_endpoints: break
    return summary


def find_matching_endpoint_gemini(spec, user_input, api_name, context=None, max_endpoints=50):
    """
    Uses Gemini to map natural language input to an API endpoint.
    Returns a tuple: (intent, path, method, op_details, gemini_hints, discovery_resp, confidence, reasoning, raw_response_text)
    """
    global last_gemini_raw_response # Access the module-level global

    spec_summary = summarize_spec_for_gemini(spec, max_endpoints)
    if not spec_summary:
        st.warning(f"No API endpoints found or summarized for '{api_name}'.")
        reason = "No endpoints available in the specification to query."
        return 'unknown', None, None, None, None, None, 0.0, reason, None

    # Simple discovery heuristic
    discovery_phrases = ["what can you do", "help", "capabilities", "available actions", "list endpoints", "tell me about yourself"]
    is_discovery = any(phrase in user_input.lower() for phrase in discovery_phrases)

    context_str = ""
    if context and isinstance(context, (list, tuple)): # Ensure context is iterable
        context_str = "\n\n## Previous Interactions Context (Recent First):\n"
        for i, interaction in enumerate(reversed(context)):
             if i >= 3: break # Limit context history in prompt
             req = interaction.get('request', {})
             resp = interaction.get('response', {})
             context_str += (
                 f"{i+1}. User: '{interaction.get('natural_language', 'N/A')}'. "
                 f"Agent Call: {req.get('method','?')} {req.get('path', '?')} (API: {req.get('api','?')}). "
                 f"Result: Status {resp.get('status', '?')}\n"
             )
        context_str += "\nUse this context to better understand the current request, if relevant."

    info_section = spec.get('info', {})
    api_title = info_section.get('title', api_name)
    api_description = info_section.get('description', 'No description provided.')

    intent_guidance = (
        'If the user is asking about the API\'s capabilities (e.g., "what can you do?", "help"), respond with the "discovery" intent.'
        if is_discovery else
        'If the user request clearly maps to a specific API call defined in the summary, respond with the "endpoint_call" intent.'
    )

    prompt = f"""
You are an AI Agent acting as a natural language interface for the API '{api_name}'.
Your goal is to understand the user's request and map it to the most appropriate API call from the summary provided, extract necessary parameters/body data, OR explain the API's capabilities if the user asks for help.

**API Information:**
Name: {api_name}
Title: {api_title}
Description: {api_description[:500]}

**Available Endpoints Summary:**
```json
{json.dumps(spec_summary, indent=2)}
```
{context_str}

**Current User Request:**
"{user_input}"

**Your Task:**
1. Analyze the user request in the context of the API '{api_name}' and previous interactions (if any).
2. Determine the user's intent:
    - "discovery": If the user asks about capabilities, help, etc.
    - "endpoint_call": If the request maps to a specific API call.
    - "unknown": If the request is unrelated, ambiguous, or cannot be fulfilled by the listed endpoints.
3. If "endpoint_call":
    - Identify the single BEST matching endpoint (`path` and `method`).
    - Extract values for required parameters (`parameters`) based on the endpoint definition and user request. If a parameter isn't mentioned, omit it unless it has a clear default or is essential.
    - Infer potential data for the request body (`requestBodyData`) if applicable, structuring it as a JSON object based on user input (e.g., for creating or updating resources).
4. If "discovery": Provide a concise natural language summary of the API's purpose and example actions (`discovery_response`).
5. Provide a confidence score (0.0-1.0) reflecting your certainty in the chosen intent and mapping.
6. Briefly explain your reasoning (`reasoning`).

**Output Format:**
Return ONLY a single valid JSON object. Do NOT include ```json``` markers or any other text outside the JSON object itself.
```json
{{
  "intent": "discovery | endpoint_call | unknown",
  "confidence": 0.9,
  "path": "/path/to/endpoint" | null,
  "method": "GET | POST | PUT | DELETE" | null,
  "parameters": {{ "param_name_in_spec": "value_from_user_request" }} | null,
  "requestBodyData": {{ "body_key": "value_from_user_request" }} | null,
  "reasoning": "Brief explanation.",
  "discovery_response": "Concise API summary and example commands." | null
}}
```
**Example - Endpoint Call:**
```json
{{
  "intent": "endpoint_call", "confidence": 0.95, "path": "/users", "method": "GET",
  "parameters": {{ "status": "active", "limit": 10 }}, "requestBodyData": null,
  "reasoning": "User wants to 'list first 10 active users', mapping to GET /users with query parameters.",
  "discovery_response": null
}}
```
**Example - Discovery:**
```json
{{
  "intent": "discovery", "confidence": 0.98, "path": null, "method": null,
  "parameters": null, "requestBodyData": null,
  "reasoning": "User asked 'What can you do?', requesting capabilities.",
  "discovery_response": "This API ('{api_name}') manages users and widgets. You can ask to 'list users', 'create a new widget', or 'get details for user 123'."
}}
```
**Example - Unknown:**
```json
{{
  "intent": "unknown", "confidence": 0.3, "path": null, "method": null,
  "parameters": null, "requestBodyData": null,
  "reasoning": "User request 'Tell me a joke' is unrelated to this API's function.",
  "discovery_response": null
}}
```

Now, process the user request for API '{api_name}': "{user_input}"
Ensure the output is ONLY the JSON object.
"""

    response_text = call_gemini(prompt) # This updates last_gemini_raw_response
    raw_response_text = last_gemini_raw_response # Capture it for returning

    if not response_text:
        return 'unknown', None, None, None, None, None, 0.0, "Gemini API call failed.", raw_response_text

    parsed_result = extract_json_from_response(response_text)

    if not parsed_result or not isinstance(parsed_result, dict):
        reason = "Failed to parse Gemini response as valid JSON."
        # Try to extract reasoning if response was just text
        if isinstance(response_text, str) and not response_text.strip().startswith('{'):
            reason += f" Raw Response Hint: {response_text[:200]}"
        return 'unknown', None, None, None, None, None, 0.0, reason, raw_response_text

    try:
        intent = parsed_result.get('intent')
        confidence = float(parsed_result.get('confidence', 0.0))
        reasoning = parsed_result.get('reasoning', 'No reasoning provided.')
        discovery_response = parsed_result.get('discovery_response')
        gemini_params = parsed_result.get('parameters') # Allow null
        gemini_body_hints = parsed_result.get('requestBodyData') # Allow null

        # Combine extracted params and body hints into a single dictionary for easier use later
        # Gemini might put body fields inside 'parameters' or 'requestBodyData'
        combined_hints = {**(gemini_params or {}), **(gemini_body_hints or {})}

        if intent == 'discovery':
            return 'discovery', None, None, None, None, discovery_response, confidence, reasoning, raw_response_text

        elif intent == 'endpoint_call':
            path = parsed_result.get('path')
            method = parsed_result.get('method')

            if not path or not method:
                return 'unknown', None, None, None, None, None, confidence, f"Gemini chose 'endpoint_call' but missing path/method. Reasoning: {reasoning}", raw_response_text

            # Basic validation: Check if path exists in the spec (method check done later)
            if path not in spec.get('paths', {}):
                 # Check variations with/without trailing slash if needed, simple check first
                 st.warning(f"Gemini suggested path '{path}' not found in the spec for API '{api_name}'.")
                 return 'unknown', None, None, None, None, None, confidence, f"Invalid path '{path}' suggested by Gemini. Reasoning: {reasoning}", raw_response_text

            method_lower = method.lower()
            # Validate method exists for the path
            if method_lower not in spec['paths'][path]:
                 st.warning(f"Gemini suggested method '{method.upper()}' not found for path '{path}' in API '{api_name}'.")
                 return 'unknown', None, None, None, None, None, confidence, f"Invalid method '{method.upper()}' for path '{path}'. Reasoning: {reasoning}", raw_response_text

            operation_details = spec['paths'][path][method_lower] # Get the operation details dict

            return 'endpoint_call', path, method_lower, operation_details, combined_hints, None, confidence, reasoning, raw_response_text

        else: # Handle 'unknown' or other unexpected intents
            return 'unknown', None, None, None, None, None, confidence, f"Intent '{intent}' reported. Reasoning: {reasoning}", raw_response_text

    except (ValueError, TypeError) as e:
        error_msg = f"Error processing parsed Gemini result: {e}\nParsed Data: {parsed_result}"
        st.error(error_msg)
        return 'unknown', None, None, None, None, None, 0.0, error_msg, raw_response_text
    except Exception as e:
        error_msg = f"Unexpected error interpreting Gemini JSON: {type(e).__name__} - {e}\nParsed Data: {parsed_result}"
        st.error(error_msg)
        return 'unknown', None, None, None, None, None, 0.0, error_msg, raw_response_text


# --- Service Discovery Specific Function ---
@st.cache_data(show_spinner="🔎 Evaluating API suitability...", ttl=3600)
def rate_api_suitability(api_name, spec_info, user_query, model_name=GEMINI_MODEL_NAME):
    """Uses Gemini to rate how suitable an API is for a given query based on description."""
    global last_gemini_raw_response
    prompt = f"""
Rate how likely the API named '{api_name}' can answer the user's query based ONLY on its title and description.
Ignore previous interactions or specific endpoints. Focus solely on the API's overall purpose vs the query's topic.
Return ONLY a single floating-point number between 0.0 (not suitable) and 1.0 (highly suitable). Do not include any other text or explanation.

API Title: {spec_info.get('title', 'N/A')}
API Description: {spec_info.get('description', 'N/A')[:500]} # Limit description length
User Query: '{user_query}'

Suitability Rating (0.0-1.0): """

    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        response_text = response.text
        last_gemini_raw_response = response_text # Store raw text

        # Try to extract a float, removing potential extra text or markdown
        match = re.search(r"(\d\.?\d*)", response_text)
        if match:
             rating = float(match.group(1))
             return max(0.0, min(1.0, rating)) # Clamp between 0 and 1
        else:
             print(f"Could not extract rating number from Gemini suitability response for {api_name}: {response_text}")
             return 0.0 # Default to 0 if no number found
    except Exception as e:
        print(f"Error during suitability rating for {api_name}: {type(e).__name__} - {e}")
        last_gemini_raw_response = f"Error: {e}" # Store error
        return 0.0 # Default to 0 on error