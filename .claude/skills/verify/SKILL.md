---
name: verify
summary: Verify the running Docker Compose backend and outbound proxy behavior.
---

# AIGCNEWS runtime verification

1. Build and recreate only the backend:
   `cd docker && sudo docker compose build backend-api && sudo docker compose up -d --no-deps --force-recreate backend-api`
2. Wait for `http://127.0.0.1:8000/docs` to return 200.
3. Drive outbound behavior inside `aigc-backend` with its real environment:
   - HTTPX request to an IP echo endpoint should show the selected proxy exit.
   - HTTPX requests to `http://aigc-backend:8000/docs` and MinIO health should remain internal.
   - Call the deployed Techmeme ingestion entry point and confirm it returns rows.
   - Call the deployed website metadata entry point with a link-local metadata URL and confirm it is rejected.
4. Probe Mihomo explicitly with `proxy=http://host.docker.internal:7897` without changing `OUTBOUND_PROXY`, then confirm the container remains configured for the Tencent SOCKS5 endpoint.

Gotchas:
- The project has no pre-existing pytest installation; runtime verification is preferred.
- On this host Docker's generic `host-gateway` resolves to `172.17.0.1`, not the custom Compose network gateway. The current deployment maps `host.docker.internal` to the verified `172.19.0.1` gateway.
- Do not print `.env` or full environment dumps; proxy URLs may eventually contain credentials.
