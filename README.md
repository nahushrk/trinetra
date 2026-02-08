# Trinetra: Self-hosted 3D Model Manager and Organizer

<img src="static/images/trinetra.jpeg" alt="Trinetra">

Trinetra is a self-hosted 3D model library focused on local organization first. It helps you manage STL files, sliced files, project assets, and metadata in one place.
Integrations like Moonraker are treated as optional connectors, with room for future ecosystem plugins (including Bambu).

**Keywords**: self-hosted 3D model manager, STL organizer, G-code library, 3D print file management, local 3D model catalog.

## Why Trinetra

- **Own your library**: keep your 3D model archive local and searchable.
- **Organize by project**: STL, G-code, images, and docs in one project view.
- **Connector optional**: works standalone; connect Moonraker (and future ecosystems) only if you want print stats and queue actions.

## Features

- **Unified Project View**: Each folder in your main model path is treated as a project, showing STL files, images, PDFs, and sliced files together.

- **Local-first Model Library**: Add and organize STL files from Thingiverse, Printables, or your own custom models.

- **Zip Import**: Upload ZIP files containing multiple assets (STL, images, PDFs), and Trinetra automatically groups them into a single project.

- **Sliced File Association**: Sliced files (`.gcode`) can be linked with original STL models, so slicing metadata and print context stay connected.

- **Search & Download**: Search your local library quickly and download model or sliced files when needed.

- **Connector-ready Architecture**: Integrations (Moonraker today, more ecosystems in future) are optional so the core app remains ecosystem-agnostic.

<img src="static/images/screenshot_1.png">
<img src="static/images/screenshot_2.png">
<img src="static/images/screenshot_3.png">
<img src="static/images/screenshot_4.png">
<img src="static/images/screenshot_5.png">

## Usage

1. **Add New Models**: Download 3D models from the web (Thingiverse, Printables, etc.) or use custom models. Upload as ZIP packages or place files in your library path.

2. **Project View**: View all files related to a project in one place (STL, images, PDFs, sliced files).

3. **Slice & Print**: Search your catalog for models, download the STL, slice in your preferred slicer, and keep generated gcode associated with the source model.

4. **Track Slicer Settings**: Trinetra keeps slicer metadata alongside the original STL where available.

## Installation

1. Clone this repository:

    ```bash
    git clone https://github.com/nahushrk/trinetra.git
    cd trinetra
    ```

2. Recommended: run with Docker (works across desktop and Linux hosts):

    ```bash
    make docker-up
    ```

3. Open your browser and go to [http://localhost:8969](http://localhost:8969) (or the host IP if running remotely).

### Native install (optional)

If you prefer a native service setup, run:

    ```bash
    ./install.sh
    ```

## Running with Docker

Docker is the recommended way to run Trinetra on most environments.

### Quick Start (Docker)

1. Install Docker (Docker Desktop on desktop OS, or Docker Engine + Compose plugin on Linux).
2. From repo root, run:

```bash
make docker-up
```

3. Open [http://localhost:8969](http://localhost:8969)

The `make docker-up` flow automatically creates data directories, writes a default Docker config (first run), and starts the app in detached mode.

### Manual Start (without Make)

```bash
./scripts/docker-setup.sh
docker compose up -d --build
```

### Data Persistence (single host path)

Docker Compose mounts one host directory by default:

- `./trinetra-data` -> `/trinetra-data`

To change the host path, edit the first line in `docker-compose.yml`:

- `x-trinetra-host-base-dir: &trinetra_host_base_dir ./trinetra-data`

Inside that directory, Trinetra uses:

- `models/` for model and project files
- `gcodes/` for sliced files
- `system/` for runtime config and SQLite database

### Docker Configuration

- Runtime config file (inside mounted base dir): `system/config.yaml`
- Default DB path in Docker: `/trinetra-data/system/trinetra.db`
- Optional Moonraker connector URL: `moonraker_url`
- Initial Docker config template in repo: `config.docker.yaml`

Default Docker connector URL is:

- `moonraker_url: "http://host.docker.internal:7125"`

This works on Docker Desktop and is also mapped for Linux hosts via `extra_hosts` in `docker-compose.yml`.

### Optional Overrides

You can still use `.env` for port override only:

- `TRINETRA_PORT`

### Operations

```bash
# Start / rebuild
make docker-up

# View logs
make docker-logs

# Stop
make docker-down
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request if you would like to contribute or report any bugs.

### Development Setup (using uv)

For development, we recommend using [uv](https://github.com/astral-sh/uv) for fast, modern Python dependency management and virtual environments.

1. Install uv (if not already):

    ```bash
    pip install uv
    ```

2. Set up the development environment:

    ```bash
    make dev-setup
    ```

3. Run formatting and tests:

    ```bash
    make format
    make test
    # or run all checks
    make all
    ```

This will create a `.venv` using uv and install all development dependencies. All development commands (format, test, etc.) are run inside this environment.

**Note:** Both native installation and Docker deployment use uv for dependency management, ensuring consistency across environments.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
