# SignalGateway Dashboard

Vue 3 + Vite dashboard for the `jh_quant.signalgateway.service_api` endpoints.

## Dev

```bash
pnpm install
pnpm dev
```

Pass the API address with a query string during browser debugging:

```bash
http://127.0.0.1:5173/?apiBase=http://127.0.0.1:8000
```

In desktop mode the preferred source is `pywebview.api.get_runtime_config()`.
