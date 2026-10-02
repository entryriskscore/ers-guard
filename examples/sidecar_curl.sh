#!/bin/sh
# Start the sidecar once (it keeps one shared cache and writes ers_state.json every cycle):
#   ERS_API_KEY=... ers-guard serve --port 8787 --file ers_state.json
curl -s "http://127.0.0.1:8787/check?symbol=ETHUSDT&side=LONG&hold=60m"; echo
curl -s "http://127.0.0.1:8787/health"; echo
