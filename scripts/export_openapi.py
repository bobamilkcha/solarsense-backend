"""Write the API's OpenAPI spec to docs/openapi.json for the frontend.

Run after changing any route or schema: `mise run export-openapi`.
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
