# SwiftLabel

**Keyboard - first image classification tool for ML practitioners who value speed and simplicity.**

![SwiftLabel Demo](assets/demo_v2.gif)

SwiftLabel is a local-only, zero-config tool that lets you classify images using keyboard shortcuts. All changes are staged until you commit them, ensuring a non-destructive workflow.

## Features

- **Keyboard-driven workflow** - Hands never leave the keyboard
- **Local-first & private** - Images never leave your machine
- **Non-destructive** - Preview all changes before committing
- **Zero config** - Open folder, define classes, start labeling
- **Session persistence** - Resume where you left off
- **Undo support** - Revert your last actions

## Installation

```bash
pip install git+https://github.com/ksavkin/SwiftLabel.git
```

Or install from source:

```bash
git clone https://github.com/ksavkin/SwiftLabel.git
cd swiftlabel
pip install -e ".[dev]"
```

## Quick Start

```bash
# Basic usage (try with included examples!)
swiftlabel ./examples --classes cat,dog,bird

# With custom port
swiftlabel ./images --classes cat,dog,bird --port 9000

# Without auto-opening browser
swiftlabel ./images --classes cat,dog,bird --no-browser
```

A browser window will open at `http://localhost:8765` where you can start labeling.

## Remote Usage (SSH)

To use SwiftLabel on a remote server (e.g., a training machine with your dataset), you can forward the port via SSH.

1.  **On your local machine**, create an SSH tunnel:
    ```bash
    # Forward local port 8001 to remote port 8001
    ssh -L 8001:localhost:8001 user@remote-host
    ```

2.  **On the remote server**, run SwiftLabel on the forwarded port:
    ```bash
    # Run with --no-browser since you're on a remote terminal
    # Use python3 -m if the 'swiftlabel' command is not in your PATH
    python3 -m swiftlabel.cli ./your_dataset --classes up,down --port 8001 --no-browser
    ```

3.  **On your local machine**, open `http://localhost:8001` in your browser.

## Restarting & Stopping

If you see `[Errno 98] address already in use`, it means a previous instance is still running.

- **To stop a running server**: Press `Ctrl+C` in the terminal.
- **To force-kill a stale server** (if Ctrl+C doesn't work or port is stuck):
  ```bash
  # Replace 8765 with your port number
  lsof -ti:8765 | xargs kill -9
  ```

### Troubleshooting Remote Usage

- **Port already in use**: If you see `[Errno 98] address already in use`, find and kill the process:
  ```bash
  lsof -ti:8001 | xargs kill -9
  ```
- **WebSocket connection fails**: If you see a `TypeError` regarding `logger` in `websockets`, upgrade the library:
  ```bash
  pip install --upgrade websockets
  ```

## Keyboard Shortcuts

### Basic Controls

| Key | Action |
|-----|--------|
| `1-9` | Assign to class 1-9 |
| `0` | Assign to class 10 (if available) |
| `D` | Mark for deletion |
| `U` | Undo last action |
| `←` / `→` | Previous / Next image |
| `Enter` | Commit all changes |
| `Esc` | Cancel / Close modal |
| `?` | Show help overlay |

### Vim-style Navigation

| Key | Action |
|-----|--------|
| `H` / `L` | Previous / Next image |
| `J` / `K` | Next / Previous image |

## How It Works

1. **Launch**: Run `swiftlabel ./images --classes cat,dog,bird`
2. **Label**: Press `1`, `2`, or `3` to classify images
3. **Review**: Press `Enter` to preview pending changes
4. **Commit**: Confirm to apply changes to filesystem

### Staging

All changes are **staged** until you commit:
- Labeled images will be moved to class folders (e.g., `cat/image.jpg`)
- Deleted images will be removed from disk
- You can undo any action before committing

### Session Persistence

SwiftLabel automatically saves your progress to `.swiftlabel/session.json`. When you restart, it resumes from where you left off.

## Data Organization

SwiftLabel supports two main workflows:

### 1. Labeling from Scratch (Flat Folder)
If you have a folder full of unsorted images:
```text
my_dataset/
  ├── image1.jpg
  ├── image2.jpg
  └── ...
```
When you commit, SwiftLabel will **create** class folders and move images into them:
```text
my_dataset/
  ├── cat/
  │   └── image1.jpg
  ├── dog/
  │   └── image2.jpg
  └── ...
```

### 2. Reviewing Existing Labels (Structured Folders)
If your images are already organized into folders:
```text
my_dataset/
  ├── cat/
  │   └── image1.jpg  <-- Auto-detected as "cat"
  ├── dog/
  │   └── image2.jpg  <-- Auto-detected as "dog"
```
SwiftLabel will read the folder names as initial labels. You can freely change labels or delete images, and changes will be applied to the file system upon commit.

## CLI Options

```
Usage: swiftlabel [OPTIONS] DIRECTORY

Arguments:
  DIRECTORY  Path to the folder containing images to classify

Options:
  -c, --classes TEXT   Comma-separated list of class names (required)
  -h, --host TEXT      Server host address [default: 127.0.0.1]
  -p, --port INTEGER   Server port [default: 8765]
  --no-browser         Don't open browser automatically
  --debug              Enable debug logging
  --version            Show version and exit
  --help               Show this message and exit
```

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- WebP (.webp)
- GIF (.gif)
- BMP (.bmp)
- TIFF (.tiff, .tif)

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/swiftlabel/swiftlabel
cd swiftlabel

# Install with dev dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=swiftlabel --cov-report=term-missing
```

### Type Checking

```bash
mypy swiftlabel/ --strict
```

### Linting

```bash
ruff check swiftlabel/
```

## API Reference

SwiftLabel exposes a REST API at `http://localhost:8765/api`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/session` | GET | Get full session state |
| `/api/stats` | GET | Get labeling statistics |
| `/api/images` | GET | List all images |
| `/api/images/{id}` | GET | Serve image file |
| `/api/label` | POST | Assign label to image |
| `/api/delete` | POST | Mark image for deletion |
| `/api/undo` | POST | Undo last action |
| `/api/changes/preview` | GET | Preview pending changes |
| `/api/changes/commit` | POST | Apply all changes |

WebSocket endpoint at `/ws` for real-time updates.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SWIFTLABEL_HOST` | 127.0.0.1 | Server bind address |
| `SWIFTLABEL_PORT` | 8765 | Server port |
| `SWIFTLABEL_DEBUG` | false | Enable debug logging |

## License

MIT License. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
