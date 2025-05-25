import streamlit as st
from gemini_agent import find_matching_endpoint_gemini, rate_api_suitability, last_gemini_raw_response
from config import COORDINATOR_MIN_CONFIDENCE, MESH_CONFIDENCE_THRESHOLD, SERVICE_DISCOVERY_MIN_SUITABILITY

# Note: These functions now also need to handle/return the raw Gemini response

def coordinator_pattern(apis, user_query, context, max_endpoints):
    """Coordinator Pattern: Central agent queries all APIs and picks the best match."""
    st.info("ℹ️ Using **Coordinator Pattern**: Querying all available APIs...")
    results = {}
    best_match = {'confidence': -1.0, 'api_name': None, 'raw_response': None}
    potential_matches = []
    aggregated_raw_responses = {}

    for api_name, spec in apis.items():
        st.write(f"Coordinator: Evaluating API '{api_name}'...")
        intent, path, method, op, params_hints, discovery, confidence, reasoning, raw_resp = find_matching_endpoint_gemini(
            spec, user_query, api_name, context, max_endpoints
        )
        aggregated_raw_responses[api_name] = raw_resp # Store individual raw response

        match_data = {
            'api_name': api_name, 'intent': intent, 'path': path, 'method': method,
            'op': op, 'params_hints': params_hints, 'discovery': discovery,
            'confidence': confidence, 'reasoning': reasoning, 'raw_response': raw_resp
        }
        potential_matches.append(match_data)

        # Track the best confident match so far (endpoint or discovery)
        if intent in ['endpoint_call', 'discovery'] and confidence > best_match['confidence']:
             best_match = match_data

    # Display results from all APIs evaluated
    with st.expander("Coordinator Evaluation Details", expanded=False):
        for match in potential_matches:
            st.caption(f"**API: {match['api_name']}** | Intent: {match['intent']} | Confidence: {match['confidence']:.2f} | Path: {match['path'] or 'N/A'} | Reason: {match['reasoning']}")

    # Select the best match if confidence is sufficient
    if best_match['api_name'] and best_match['confidence'] >= COORDINATOR_MIN_CONFIDENCE:
        st.success(f"✅ Coordinator selected API '{best_match['api_name']}' (Confidence: {best_match['confidence']:.2f}).")
        # Return details of the best match, including its specific raw response
        return (best_match['api_name'], best_match['intent'], best_match['path'], best_match['method'],
                best_match['op'], best_match['params_hints'], best_match['discovery'],
                best_match['confidence'], best_match['reasoning'], best_match['raw_response'])
    else:
        st.warning("Coordinator: No suitable endpoint found across any API with sufficient confidence.")
        # Find the one with the highest confidence, even if low, to return its reasoning and raw response
        best_reasoning = "Coordinator couldn't find a match in any API."
        highest_conf_raw_response = None
        if potential_matches:
             top_match = max(potential_matches, key=lambda x: x['confidence'])
             best_reasoning = top_match['reasoning']
             highest_conf_raw_response = top_match['raw_response']

        return None, 'unknown', None, None, None, None, None, 0.0, best_reasoning, highest_conf_raw_response


def mesh_pattern(apis, user_query, context, max_endpoints, primary_api_name):
    """Mesh Pattern: Primary agent tries first, then asks others if unsure."""
    st.info(f"ℹ️ Using **Mesh Pattern**: Starting with primary API '{primary_api_name}'...")

    # 1. Query the primary API
    primary_spec = apis.get(primary_api_name)
    if not primary_spec:
         st.error(f"Mesh Error: Primary API '{primary_api_name}' not found.")
         return None, 'unknown', None, None, None, None, None, 0.0, "Primary API not found.", None

    primary_intent, primary_path, primary_method, primary_op, primary_hints, primary_discovery, primary_confidence, primary_reasoning, primary_raw_resp = find_matching_endpoint_gemini(
        primary_spec, user_query, primary_api_name, context, max_endpoints
    )

    # 2. If confident enough or discovery, use the primary result
    is_primary_sufficient = (primary_intent == 'endpoint_call' and primary_confidence >= MESH_CONFIDENCE_THRESHOLD) or \
                              primary_intent == 'discovery'

    if is_primary_sufficient:
        st.success(f"✅ Mesh: Primary API '{primary_api_name}' handled the request (Confidence: {primary_confidence:.2f}).")
        return (primary_api_name, primary_intent, primary_path, primary_method, primary_op,
                primary_hints, primary_discovery, primary_confidence, primary_reasoning, primary_raw_resp)

    st.warning(f"Mesh: Primary API '{primary_api_name}' result uncertain (Confidence: {primary_confidence:.2f}). Querying other APIs...")

    # 3. If primary is uncertain, query other APIs
    best_alt_match = {
        'api_name': primary_api_name, 'intent': primary_intent, 'path': primary_path,
        'method': primary_method, 'op': primary_op, 'params_hints': primary_hints,
        'discovery': primary_discovery, 'confidence': primary_confidence,
        'reasoning': primary_reasoning, 'raw_response': primary_raw_resp
    }
    aggregated_raw_responses = {primary_api_name: primary_raw_resp}

    for name, spec in apis.items():
        if name == primary_api_name: continue # Skip primary

        st.write(f"Mesh: Evaluating alternative API '{name}'...")
        alt_intent, alt_path, alt_method, alt_op, alt_hints, alt_discovery, alt_confidence, alt_reasoning, alt_raw_resp = find_matching_endpoint_gemini(
            spec, user_query, name, context, max_endpoints
        )
        aggregated_raw_responses[name] = alt_raw_resp

        # Select the alternative if its confidence is significantly higher OR it's discovery and primary wasn't
        significant_improvement = alt_intent != 'unknown' and alt_confidence > best_alt_match['confidence'] + 0.1
        is_discovery_upgrade = alt_intent == 'discovery' and best_alt_match.get('intent') != 'discovery'

        if significant_improvement or is_discovery_upgrade:
            best_alt_match = {
                'api_name': name, 'intent': alt_intent, 'path': alt_path, 'method': alt_method,
                'op': alt_op, 'params_hints': alt_hints, 'discovery': alt_discovery,
                'confidence': alt_confidence, 'reasoning': alt_reasoning, 'raw_response': alt_raw_resp
            }
            st.info(f"Mesh: Found potentially better match in '{name}' (Confidence: {alt_confidence:.2f})")

    # Decide final outcome
    selected_api_name = best_alt_match['api_name']
    final_confidence = best_alt_match['confidence']

    if selected_api_name != primary_api_name:
         st.success(f"✅ Mesh: Selected alternative API '{selected_api_name}' (Confidence: {final_confidence:.2f}).")
    else:
         # Primary was chosen, but was it good enough? Check final confidence against a lower threshold maybe?
         if final_confidence < COORDINATOR_MIN_CONFIDENCE: # Use coordinator threshold as a general 'is it usable' check
              st.warning(f"Mesh: No suitable alternative found. Initial result from '{primary_api_name}' remains uncertain and below threshold.")
              # Return primary's details but maybe flag as unknown? Or stick with primary's intent? Let's return primary's result as is.
         else:
              st.info(f"Mesh: No better alternative found. Using initial result from '{primary_api_name}'.")

    # Return the details of the best match found (either primary or alternative)
    return (best_alt_match['api_name'], best_alt_match['intent'], best_alt_match['path'],
            best_alt_match['method'], best_alt_match['op'], best_alt_match['params_hints'],
            best_alt_match['discovery'], best_alt_match['confidence'],
            best_alt_match['reasoning'], best_alt_match['raw_response']) # Return the specific raw response


def service_discovery_pattern(apis, user_query, context, max_endpoints):
    """Service Discovery Pattern: Agents consult a 'directory' (rating function) to find the best API."""
    st.info("ℹ️ Using **Service Discovery Pattern**: Evaluating API suitability...")
    api_matches = []
    suitability_raw_responses = {}

    # 1. Rate each API's suitability
    for name, spec in apis.items():
        # Rating uses a separate Gemini call, capture its raw response if needed (might be just the number)
        score = rate_api_suitability(name, spec.get('info', {}), user_query)
        # last_gemini_raw_response from the rating call isn't easily captured here unless rate_api_suitability returns it
        # For now, we focus on the main endpoint finding raw response later
        api_matches.append({'name': name, 'score': score})
        st.write(f"Service Discovery: API '{name}' suitability score: {score:.2f}")

    # 2. Sort by score and select the best match
    api_matches.sort(key=lambda x: x['score'], reverse=True)

    best_api_name = None
    best_score = 0.0
    if api_matches:
        best_api_name = api_matches[0]['name']
        best_score = api_matches[0]['score']

    # Check threshold
    if not best_api_name or best_score < SERVICE_DISCOVERY_MIN_SUITABILITY:
        st.warning(f"Service Discovery: No API found with suitability score >= {SERVICE_DISCOVERY_MIN_SUITABILITY}.")
        best_reasoning = "Service Discovery couldn't find a suitable API based on descriptions and threshold."
        # Optionally run find_matching_endpoint on highest rated (even if low) to get *some* reasoning/raw_resp
        final_raw_resp = None
        if best_api_name:
             _, _, _, _, _, _, _, _, best_reasoning, final_raw_resp = find_matching_endpoint_gemini(
                   apis[best_api_name], user_query, best_api_name, context, max_endpoints)
             best_reasoning = f"Suitability low ({best_score:.2f}). Best guess reasoning: {best_reasoning}"

        return None, 'unknown', None, None, None, None, None, 0.0, best_reasoning, final_raw_resp

    st.success(f"✅ Service Discovery: Selected API '{best_api_name}' (Score: {best_score:.2f}).")

    # 3. Call the selected API's agent to get the specific endpoint
    selected_spec = apis[best_api_name]
    intent, path, method, op, params_hints, discovery, confidence, reasoning, raw_resp = find_matching_endpoint_gemini(
        selected_spec, user_query, best_api_name, context, max_endpoints
    )

    # Add context about why this API was chosen
    final_reasoning = f"Service Discovery chose API '{best_api_name}' (Suitability: {best_score:.2f}).\nAgent Reason: {reasoning}"

    return best_api_name, intent, path, method, op, params_hints, discovery, confidence, final_reasoning, raw_resp