# API-as-Agent (5*A) - AI-Powered API Interface

A Streamlit application that transforms OpenAPI specifications into intelligent AI agents capable of understanding natural language queries and executing API calls automatically.

## 🌟 Features

### Core Capabilities
- **Natural Language API Interaction**: Ask APIs questions in plain English instead of reading documentation [1](#0-0) 
- **Automatic Endpoint Discovery**: AI agent analyzes OpenAPI specs and finds the right endpoints for your queries [2](#0-1) 
- **Authentication Handling**: Automatic detection and configuration of API authentication schemes [3](#0-2) 
- **Request Parameter Generation**: Auto-fills API parameters based on natural language understanding [4](#0-3) 

### Multi-API Coordination Patterns
The application supports three coordination patterns for handling multiple APIs simultaneously:

1. **Coordinator Pattern**: Central control evaluates all APIs and selects the best match [5](#0-4) 
2. **Mesh Pattern**: Primary API with peer consultation for complex queries [6](#0-5) 
3. **Service Discovery Pattern**: Directory-based API selection [7](#0-6) 

### User Interface Features
- **Interactive Forms**: Dynamic form generation for API parameters [8](#0-7) 
- **Request History**: Track and review previous API interactions [9](#0-8) 
- **cURL Export**: Generate cURL commands for API requests [10](#0-9) 
- **Real-time Authentication Status**: Monitor API authentication configuration [11](#0-10) 

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Google Gemini API key
- OpenAPI 3.0 specification files (YAML or JSON)

### Installation

1. Clone the repository
2. Install dependencies (requirements need to be documented)
3. Set up environment variables:
   ```
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

### Configuration
The application uses Google Gemini for natural language processing [12](#0-11) . Configure your API key either in a `.env` file or Streamlit secrets [13](#0-12) .

### Running the Application
```bash
streamlit run app.py
```

## 📖 Usage

1. **Upload OpenAPI Specs**: Use the sidebar to upload one or more OpenAPI 3.0 specification files [14](#0-13) 
2. **Select Active API**: Choose which API to interact with [15](#0-14) 
3. **Choose Coordination Pattern**: For multiple APIs, select how they should coordinate [16](#0-15) 
4. **Ask Natural Language Questions**: Type your request in plain English [17](#0-16) 
5. **Review and Execute**: The AI will suggest an API call which you can review and execute [18](#0-17) 

## 🏗️ Architecture

### Core Components
- **Main Application**: Streamlit-based user interface and workflow orchestration [19](#0-18) 
- **Gemini Agent**: Natural language processing and endpoint matching [20](#0-19) 
- **Coordination Engine**: Multi-API pattern implementations [21](#0-20) 
- **OpenAPI Utils**: Specification parsing and validation [22](#0-21) 
- **Authentication Module**: Security scheme handling [3](#0-2) 

### Configuration Parameters
- Maximum history entries: 10 [23](#0-22) 
- Gemini model: gemini-1.5-flash [24](#0-23) 
- Request timeout: 30 seconds [25](#0-24) 
- Confidence thresholds for coordination patterns [26](#0-25) 

## 📁 Project Structure

```
api-as-agent/
├── app.py                 # Main Streamlit application
├── config.py             # Configuration and constants
├── gemini_agent.py       # AI agent implementation
├── coordination.py       # Multi-API coordination patterns
├── openapi_utils.py      # OpenAPI specification utilities
├── auth.py              # Authentication handling
├── api_request.py       # API request execution
├── ui_components.py     # UI component functions
├── utils.py             # General utilities
├── .devcontainer/       # Development container configuration
└── LICENSE             # License file
```

## 🤝 Contributing

This project implements the API-as-an-AI-Agent (5*A) concept and still under the development.
