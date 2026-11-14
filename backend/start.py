"""Production entry point. Run from the repository root with python -m backend.start."""
import os

import uvicorn


def main():
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    uvicorn.run(
        "backend.app.main:app", host="0.0.0.0", port=port,
        workers=1, reload=False,
        # Render terminates TLS and forwards requests over its private proxy.
        # Only use this entry point behind a trusted ingress such as Render.
        proxy_headers=True, forwarded_allow_ips="*",
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
