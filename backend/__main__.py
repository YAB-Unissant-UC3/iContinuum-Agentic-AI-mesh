"""Start from the repository root with: python -m backend"""

import argparse

from .server import create_server


def main():
    parser = argparse.ArgumentParser(description="Start the local iContinuum workspace.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        server = create_server(args.port)
    except OSError as exc:
        parser.exit(1, "Could not start server: {}. Try --port 8001.\n".format(exc))
    print("iContinuum workspace: http://127.0.0.1:{}".format(args.port), flush=True)
    print("Local prototype. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
