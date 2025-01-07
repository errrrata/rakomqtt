#!/usr/bin/env python3
import argparse
import logging
import sys
import os
import asyncio
from typing import NoReturn, Optional
import signal
from dataclasses import dataclass
from contextlib import suppress

from rakomqtt.bridge import run_bridge
from rakomqtt.const import __version__, REQUIRED_PYTHON_VER

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class AppConfig:
    debug: bool
    rako_bridge_host: Optional[str]
    mqtt_host: str
    mqtt_user: str
    mqtt_password: str
    default_fade_rate: str = "medium"

def validate_python() -> NoReturn | None:
    """Validate that the right Python version is running."""
    if sys.version_info[:3] < REQUIRED_PYTHON_VER:
        print(
            "Home Assistant requires at least Python {}.{}.{}".format(
                *REQUIRED_PYTHON_VER
            )
        )
        sys.exit(1)
    return None

def get_args() -> AppConfig:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="rakomqtt: bridge between rako bridge and mqtt iot bus"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Start rakomqtt in debug mode",
        default=False
    )
    parser.add_argument(
        "--rako-bridge-host",
        type=str,
        help="host name/ip of the rako bridge",
    )
    parser.add_argument(
        "--mqtt-host",
        type=str,
        required=False,
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
    parser.add_argument(
        "--default-fade-rate",
        type=str,
        choices=["instant", "fast", "medium", "slow", "very_slow", "extra_slow"],
        default="medium",
        help="Default fade rate when not specified in command",
    )

    args = parser.parse_args()

    if os.path.exists('/data/options.json'):
        import json
        with open('/data/options.json') as f:
            options = json.load(f)
            # Override arguments with options from Supervisor
            args.rako_bridge_host = options.get('rako_bridge_host', args.rako_bridge_host)
            args.mqtt_host = options.get('mqtt_host', args.mqtt_host)
            args.mqtt_user = options.get('mqtt_user', args.mqtt_user)
            args.mqtt_password = options.get('mqtt_password', args.mqtt_password)
            args.debug = options.get('debug', args.debug)
            args.default_fade_rate = options.get('default_fade_rate', args.default_fade_rate)

    return AppConfig(
        debug=args.debug,
        rako_bridge_host=args.rako_bridge_host,
        mqtt_host=args.mqtt_host,
        mqtt_user=args.mqtt_user,
        mqtt_password=args.mqtt_password,
        default_fade_rate=args.default_fade_rate
    )


def setup_logging(debug: bool = False) -> None:
    """Configure logging settings."""
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    log_level = logging.DEBUG if debug else logging.INFO

    # Configure root logger
    logging.basicConfig(
        format=fmt,
        datefmt=datefmt,
        level=log_level,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Set specific loggers levels
    if debug:
        for logger_name in ["rakomqtt", "paho.mqtt"]:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
    else:
        # When not in debug mode, keep these at INFO or higher
        logging_configs = {
            "requests": logging.WARNING,
            "urllib3": logging.WARNING,
            "asyncio": logging.INFO,
            "aiohttp": logging.INFO
        }
        for logger_name, level in logging_configs.items():
            logging.getLogger(logger_name).setLevel(level)

async def shutdown(signal: signal.Signals, loop: asyncio.AbstractEventLoop) -> None:
    """Handle shutdown gracefully."""
    _LOGGER.info(f"Received signal {signal.name}, initiating graceful shutdown...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    # Set shutdown flag
    loop.shutdown_flag = True

    # Cancel all tasks
    for task in tasks:
        task.cancel()
        _LOGGER.debug(f"Cancelling task: {task.get_name()}")

    _LOGGER.info(f"Cancelling {len(tasks)} outstanding tasks")

    # Wait for all tasks to complete with a timeout
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*tasks, return_exceptions=True)

    # Stop accepting new tasks
    loop.stop()

    _LOGGER.info("Shutdown complete")

async def run() -> NoReturn | None:
    """Run the application."""
    validate_python()
    config = get_args()
    setup_logging(config.debug)

    _LOGGER.debug('Running the rakomqtt bridge')

    # Get the event loop
    loop = asyncio.get_running_loop()

    # Add shutdown flag attribute
    setattr(loop, 'shutdown_flag', False)

    # Setup signal handlers
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(
                shutdown(s, loop),
                name=f"shutdown-{s.name}"
            )
        )

    try:
        await run_bridge(
            config.rako_bridge_host,
            config.mqtt_host,
            config.mqtt_user,
            config.mqtt_password
        )
    except KeyboardInterrupt:
        _LOGGER.info("Received keyboard interrupt, initiating shutdown...")
    except Exception as e:
        _LOGGER.error(f"Bridge crashed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Ensure cleanup in case of any exit
        if not loop.shutdown_flag:
            await shutdown(signal.SIGTERM, loop)
    return None

def main() -> NoReturn | None:
    """Entry point for the application."""
    try:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        else:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(run())
    except KeyboardInterrupt:
        _LOGGER.info("Received keyboard interrupt during startup")
    finally:
        try:
            loop.close()
        except Exception as e:
            _LOGGER.error(f"Error closing event loop: {e}")

if __name__ == '__main__':
    sys.exit(main() or 0)
