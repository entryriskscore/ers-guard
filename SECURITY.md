# Security

## Reporting a problem
Use the contact form at https://entryriskscore.com/support (category "API and MCP") and describe the issue. Please do
not open a public issue for anything that could expose keys or users.

## Keys
- Never commit an API key. Guard reads `ERS_API_KEY` from the environment; `tools/live_check.py` reads it from a file.
- Guard never logs the key; the sidecar listens on 127.0.0.1 only.
- If a key leaks, create a new one in the dashboard (API & MCP): the old key stops working at once.
