"""Local entrypoint. All paths remain anchored to this project."""

import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run("dataflow.api:app", host=args.host, port=args.port)
