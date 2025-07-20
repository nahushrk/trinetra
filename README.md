# Trinetra: Local 3D Printing Catalog for Klipper

<img src="static/images/trinetra.jpeg" alt="Trinetra">

Trinetra, is a companion web app for the Klipper 3D printing software. It serves as a local 3D printing catalog to help you manage your STL files and gcode efficiently, especially for users
downloading from websites like Thingiverse, Printables, or using custom models.

## Features

- **Unified View for Projects**: Each folder within your main project path is treated as a project, showing all STL, images, PDFs, and gcode files associated with that project.

- **Manage STL Files**: Add any STL file to your catalog by uploading it, including those downloaded from the web or custom 3D models.

- **Zip File Support**: Upload zip files containing multiple files (STL, images, PDFs), and Trinetra will automatically categorize them under a single project.

- **Automatic gcode Association**: Gcode files are pulled from `~/printer_data/gcode` and automatically linked with the original STL files, allowing you to track the gcode files with the original
  model and slicing parameters used.

- **Search & Slice**: Search for models in your catalog, download STL files, slice them in your preferred slicer (such as Cura), and then upload the gcode back to Klipper.

- **Slicer Integration**: When using a slicer (like Cura) with Klipper, Trinetra can link the generated gcode back to the original STL file, keeping track of slicer settings.

<img src="static/images/screenshot_1.png" alt="Homepage shows all stl files in all folders">
<img src="static/images/screenshot_2.png" alt="Folder view shows all stl files in the folder">
<img src="static/images/screenshot_3.png" alt="Folder view shows associated gcode files">
<img src="static/images/screenshot_4.png" alt="Folder view shows associated image and PDF files">

## Usage

1. **Add New Models**: Download 3D models from the web (Thingiverse, Printables, etc.) or use custom models. Upload them (either as individual files or zip archives) into Trinetra.

2. **Project View**: View all files related to a project in one place (STL, images, PDFs, gcode).

3. **Slice & Print**: Search your catalog for models, download the STL, slice it in your slicer of choice, and upload the gcode back to Klipper.

4. **Track Slicer Settings**: Trinetra tracks the slicer settings for each gcode and shows them alongside the original STL.

## Installation

1. Clone this repository:

    ```bash
    git clone https://github.com/nahushrk/trinetra.git
    cd trinetra
    ```

2. Install and start the app:

    ```bash
    ./install.sh
    ```


3. Open a browser and access Trinetra at `http://klipper.local:8969`.

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

For production deployment, use a standard venv and pip as described in the Installation section above.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
