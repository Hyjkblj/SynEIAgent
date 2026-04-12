from __future__ import annotations

import argparse
import asyncio

from .config import load_config
from .server import GatewayServer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SynEIAgent Gateway")
    parser.add_argument("--config", type=str, default=None, help="Path to JSON config file")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    cfg = load_config(args.config)
    server = GatewayServer(cfg)
    await server.start()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
