#!/usr/bin/python
import argparse
import logging
import sys
import asyncio

from rakomqtt.bridge import run_bridge
from rakomqtt.const import __version__, REQUIRED_PYTHON_VER

_LOGGER = logging.getLogger(__name__)

def validate_python() -> None:
    """Validate that the right Python version is running."""
    if sys.version_info[:3] < REQUIRED_PYTHON_VER:
        print(
            "Home Assistant requires at least Python {}.{}.{}".format(
                *REQUIRED_PYTHON_VER
            )
        )
        sys.exit(1)

def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="rakomqtt: bridge between rako bridge and mqtt iot bus"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--debug", action="store_true", help="Start rakomqtt in debug mode", default=False
    )
    parser.add_argument(
        "--rako-bridge-host",
        type=str,
        help="host name/ip of the rako bridge",
    )
    parser.add_argument(
        "--mqtt-host",
        type=str,
        required=True,
        help="host name/ip of the mqtt server",
    )
    parser.add_argument(
        "--mqtt-user",
        type=str,
        required=True,
        help="username to use when logging into the mqtt server",
    )
    parser.add_argument(
        "--mqtt-password",
        type=str,
        required=True,
        help="password to use when logging into the mqtt server",
    )

    arguments = parser.parse_args()
    return arguments

def setup_logging(debug: bool = False) -> None:
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    log_level = logging.DEBUG if debug else logging.INFO
    
    # Configure root logger
    logging.basicConfig(format=fmt, datefmt=datefmt, level=log_level)
    
    # Set specific loggers to DEBUG when in debug mode
    if debug:
        logging.getLogger("rakomqtt").setLevel(logging.DEBUG)
        logging.getLogger("paho.mqtt").setLevel(logging.DEBUG)
    else:
        # When not in debug mode, keep these at INFO or higher
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.INFO)
        logging.getLogger("aiohttp").setLevel(logging.INFO)

async def run():
    validate_python()
    args = get_args()
    setup_logging(args.debug)

    _LOGGER.debug('Running the rakomqtt bridge')
    
    try:
        await run_bridge(
            args.rako_bridge_host,
            args.mqtt_host,
            args.mqtt_user,
            args.mqtt_password
        )
    except KeyboardInterrupt:
        _LOGGER.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        _LOGGER.error(f"Bridge crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(run())
