"""Start from the repository root with: python -m backend"""

import argparse

from .server import create_server
from .providers import brief_generator_from_environment


def main():
    parser = argparse.ArgumentParser(description="Start the local iContinuum workspace.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sample-dir", help="Folder containing manifest.json and synthetic .txt files.")
    parser.add_argument("--data-dir", help="Folder for the local audit.jsonl log (default: .runtime).")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        generator = brief_generator_from_environment()
        server = create_server(args.port, data_dir=args.data_dir, sample_dir=args.sample_dir, brief_generator=generator)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, "Could not start server: {}. Try --port 8001.\n".format(exc))
    print("iContinuum workspace: http://127.0.0.1:{}".format(args.port), flush=True)
    print("Brief mode: {}. Requirements Checker: deterministic. Synthetic data only. Ctrl+C stops the server.".format(
        "{} selected with deterministic fallback".format(generator.provider)
        if generator is not None and generator.enabled else "deterministic demo (live generation disabled)"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
