# Tripwire frontend

React + Vite + TypeScript, Tailwind, React Flow, Recharts. Talks to the FastAPI
backend over REST and the `/events` WebSocket.

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api -> http://127.0.0.1:8000
```

Run the backend first: `uv run uvicorn api.main:build --factory --app-dir backend`.

See [DESIGN.md](DESIGN.md) for the visual identity. Screens: Assistant (chat +
live flow graph), Memory, Routines, Evidence (AgentDojo charts).
