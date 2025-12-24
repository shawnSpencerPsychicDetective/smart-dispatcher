# Smart Dispatcher

Smart Dispatcher is an autonomous facility-management system that leverages multimodal AI to intake tenant maintenance requests, verify context (warranty, tenant, calendar availability), and dispatch appropriate work orders via email or internal scheduling. It integrates a real‑time voice agent (LiveKit + OpenAI Realtime API) with a backend operation server implemented using the Model Context Protocol (FastMCP).

---

## Table of contents

* [Key features](#key-features)
* [Architecture overview](#architecture-overview)
* [Workflow](#workflow)
* [Project structure](#project-structure)
* [Prerequisites](#prerequisites)
* [Installation](#installation)
* [Configuration (environment variables)](#configuration-environment-variables)
* [Database initialization](#database-initialization)
* [Running the system (development)](#running-the-system-development)
* [Development notes](#development-notes)

---

## Key features

* Real-time voice intake using LiveKit and OpenAI Realtime API.
* Context-aware decisioning via an MCP server (FastMCP): tenant lookup, asset lookup, warranty validation.
* Conditional dispatch: routes to manufacturer warranty support or internal maintenance scheduling depending on warranty status.
* Admin dashboard (Streamlit) for monitoring tenants, assets, and dispatch logs.
* Local development utilities: mock SMTP server for intercepting outgoing mail and database seeding script.

---

## Architecture overview

The system follows a client-server pattern:

* **Voice Agent (frontend)**

  * LiveKit worker handles audio streaming and voice session lifecycle.
  * OpenAI Realtime API is used for intent detection and multimodal interactions.
  * The voice agent queries the MCP Server to retrieve tenant and asset context required to make dispatch decisions.

* **MCP Server (backend)**

  * Implemented with FastMCP, exposes tools for DB lookups (SQLite), calendar availability checks, and dispatch actions (email/calendar APIs).
  * Responsible for business logic and execution of final actions (send emails, create internal work orders).

* **Admin Dashboard**

  * Streamlit app that visualizes tenants, assets, warranty status, and dispatch history.

* **Data & Local services**

  * SQLite database (data/maintenance.db) stores tenant records, assets, warranty metadata, and dispatch logs.
  * `scripts/mock_smtp.py` runs a local SMTP server (port 1025) for safe email testing.

---

## Workflow

1. Tenant speaks to the voice agent (e.g. “My dishwasher is broken”).
2. Voice agent performs intent detection and extracts key entities (tenant identity, asset, issue).
3. Voice agent queries the MCP Server for tenant and asset context.
4. MCP Server checks warranty status and calendar availability.
5. Dispatch decision:

   * **Warranty active** — MCP Server emails the manufacturer/support contact with the manufacturer warranty payload.
   * **Warranty expired** — MCP Server books an internal maintenance slot and emails the property manager with the work order details.
6. Admin dashboard updates with the dispatch record and status.

---

## Project structure

```text
smart-dispatcher/
├── data/                   # SQLite database storage (data/maintenance.db)
├── scripts/
│   ├── mock_smtp.py        # Local debugging SMTP server (default port 1025)
│   └── setup_database.py   # Database seeding script
├── src/
│   ├── services/           # Business logic (calendar, email, execution helpers)
│   ├── dashboard.py        # Streamlit admin interface
│   ├── mcp_server.py       # Model Context Protocol server definition (FastMCP)
│   └── voice_agent.py      # LiveKit worker / OpenAI Realtime integration
└── requirements.txt        # Python dependencies
```

---

## Prerequisites

* Python 3.12
* LiveKit Cloud project (URL + API key/secret)
* OpenAI API key with Realtime access
* Langfuse API key (optional, for observability)

---

## Installation

1. Clone the repository:

```bash
git clone <repository_url>
cd smart-dispatcher
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create and populate the environment variables file (`.env`) — see the next section for a recommended template.

---

## Configuration (environment variables)

Create a `.env` file at the repository root with the following variables (example values shown as placeholders):

```env
OPENAI_API_KEY=sk-proj-....
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LANGFUSE_SECRET_KEY = "sk-lf-..."
LANGFUSE_PUBLIC_KEY = "pk-lf-..."
LANGFUSE_HOST = "https://cloud.langfuse.com"
```

**Notes:**

* For local development, `SMTP_HOST` and `SMTP_PORT` default to the mock SMTP server (`localhost:1025`).
* Ensure secret keys are never committed to version control.

---

## Database initialization

Seed or initialize the SQLite database with the provided script:

```bash
python scripts/setup_database.py
```

This will create `data/maintenance.db` and populate it with sample tenants, assets, and warranty entries suitable for development and testing.

---

## Running the system (development)

The system requires three processes during development: the mock SMTP server, the Streamlit admin dashboard, and the voice agent which also starts the MCP server.

1. **Start mock SMTP server** (intercepts outgoing emails locally):

```bash
python scripts/mock_smtp.py
# Listening on: localhost:1025
```

2. **Start admin dashboard** (Streamlit):

```bash
streamlit run src/dashboard.py
# Default URL: http://localhost:8501
```

3. **Start voice agent** (spawns MCP server and LiveKit worker):

```bash
python -m src.voice_agent start
```

**Typical development flow:**

* Reproduce an issue by speaking to the voice agent via a connected LiveKit session.
* Observe the decision-making and outgoing emails via the Streamlit dashboard and mock SMTP console.

---

## Development notes

* **Linting:** The project follows PEP 8. A `.flake8` file is included; run `flake8` before submitting changes.
* **MCP integration:** `voice_agent.py` spawns `mcp_server.py` as a subprocess (using configured `StdioServerParameters`) and communicates over the MCP protocol to request tools and execution.
* **Testing:** Unit tests should mock external services (LiveKit, OpenAI Realtime, SMTP). Use the included mock SMTP for email-related tests.
* **Observability:** Langfuse hooks can be enabled to record traces of agent interactions. Keep API keys out of VCS.