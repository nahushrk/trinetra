import os
import argparse
import gunicorn.app.base
import yaml

from app import create_app


class GunicornApp(gunicorn.app.base.BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            self.cfg.set(key, value)

    def load(self):
        return self.application


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Start Trinetra server with specified config")
    parser.add_argument(
        "--config", "-c", default="config.yaml", help="Path to config file (default: config.yaml)"
    )
    parser.add_argument("--port", "-p", type=int, help="Override port from config file")
    parser.add_argument(
        "--workers", "-w", type=int, help="Override number of workers from config file"
    )
    parser.add_argument(
        "--threads", "-t", type=int, help="Override number of threads from config file"
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Override log level from config file",
    )

    args = parser.parse_args()

    # Load config file
    config_file = args.config
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Config file '{config_file}' not found.")

    # Read config file
    with open(config_file) as file:
        config_data = yaml.safe_load(file)

    # Override config with command line arguments if provided
    if args.port:
        config_data["port"] = args.port
    if args.workers:
        config_data["workers"] = args.workers
    if args.threads:
        config_data["threads"] = args.threads
    if args.log_level:
        config_data["log_level"] = args.log_level

    # Set up Gunicorn options
    options = {
        "bind": f"0.0.0.0:{config_data.get('port', 8969)}",
        "workers": config_data.get("workers", 1),
        "threads": config_data.get("threads", 2),
        "loglevel": config_data.get("log_level", "debug"),
        "accesslog": config_data.get("accesslog", "gunicorn.log"),
        "errorlog": config_data.get("errorlog", "gunicorn.log"),
    }

    # Create the app with the correct config
    app = create_app(config_file=config_file)

    # Start Gunicorn with the Flask app
    GunicornApp(app, options).run()
