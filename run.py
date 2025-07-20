import os

import gunicorn.app.base
import yaml

from app import app


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
    # Load config.yaml from the local directory
    config_file = os.path.join(os.path.dirname(__file__), "config.yaml")

    # Read config.yaml file
    if os.path.exists(config_file):
        with open(config_file) as file:
            config_data = yaml.safe_load(file)
    else:
        raise FileNotFoundError("config.yaml not found in the local directory.")

    # Validate required config values
    if "log_level" not in config_data:
        raise ValueError("log_level must be specified in config.yaml")

    # Set up Gunicorn options using config file values
    options = {
        "bind": f"0.0.0.0:{config_data.get('port', 8969)}",
        "workers": config_data.get("workers", 1),
        "threads": config_data.get("threads", 2),
        "loglevel": config_data["log_level"],
        "logfile": config_data.get("log_file", "trinetra.log"),
    }

    # Start Gunicorn with the Flask app
    GunicornApp(app, options).run()
