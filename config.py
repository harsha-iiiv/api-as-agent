# config.py
import os
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

# --- Environment Setup ---
load_dotenv()

def get_gemini_api_key():
    """Retrieves the Gemini API key from env or Streamlit secrets."""
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        return api_key
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.info("🔑 Using GEMINI_API_KEY from Streamlit secrets.")
        return api_key
    except (KeyError, st.errors.StreamlitSecretNotFoundError):
        st.error("🚨 GEMINI_API_KEY not found! Please set it in your .env file or Streamlit secrets.")
        st.stop() # Stop execution if key is missing

# Try to get the Gemini API key - handle exceptions for testing without it
try:
    GEMINI_API_KEY = get_gemini_api_key()
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    st.warning(f"Error configuring Gemini API: {e}")
    GEMINI_API_KEY = None

# --- Constants ---
MAX_HISTORY = 10 # Limit context history length
GEMINI_MODEL_NAME = 'gemini-1.5-flash' # Or 'gemini-pro'
# Set safety settings if needed (can be passed during model.generate_content)
# DEFAULT_SAFETY_SETTINGS = [
#     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
#     # Add others as needed
# ]

# Default API Base URL if not found in spec or env
DEFAULT_API_BASE_URL = 'https://petstore.swagger.io'  # Changed to include full URL with scheme

# Confidence threshold for considering a primary API result sufficient in Mesh pattern
MESH_CONFIDENCE_THRESHOLD = 0.65
# Minimum confidence threshold for Coordinator pattern to accept a result
COORDINATOR_MIN_CONFIDENCE = 0.4
# Minimum suitability score threshold for Service Discovery pattern
SERVICE_DISCOVERY_MIN_SUITABILITY = 0.4
# Timeout for external HTTP requests (auth, API calls)
REQUEST_TIMEOUT_SECONDS = 30