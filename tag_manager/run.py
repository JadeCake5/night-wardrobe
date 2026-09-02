from pathlib import Path

import uvicorn


PACKAGE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    uvicorn.run(
        "tag_manager.app:app",
        host="127.0.0.1",
        port=8765,
        reload=True,
        reload_dirs=[str(PACKAGE_DIR)],
    )
