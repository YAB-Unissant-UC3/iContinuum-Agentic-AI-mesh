"""Run with: python -m document_reader path/to/document.txt [...]"""

import argparse
import json

from .reader import read_document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read UTF-8 .txt files and print JSON with source line numbers."
    )
    parser.add_argument("files", nargs="+", help="One or more .txt file paths.")
    args = parser.parse_args()

    documents = [read_document(file_path) for file_path in args.files]
    # Escapes keep JSON safe for Windows consoles; decoding restores the text.
    print(json.dumps({"documents": documents}, indent=2, ensure_ascii=True))
    return 1 if any(document["status"] == "error" for document in documents) else 0


if __name__ == "__main__":
    raise SystemExit(main())
