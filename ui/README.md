# CleanHouse Modular UI Architecture

This directory contains the modular UI architecture for the CleanHouse application. The UI has been refactored from a single `ui.py` file into a clean, maintainable folder structure.

## Architecture Overview

The modular UI follows a separation of concerns pattern with the following structure:

```
ui/
├── __init__.py          # Module initialization and exports
├── main.py              # Main entry point (replaces ui.py)
├── layout.py            # Window layout, geometry, and styling
├── events.py            # UI event bindings and window management
├── hooks.py             # Actions that trigger CleanHouse logic
├── widgets/             # Custom widget components
│   ├── __init__.py
│   ├── terminal.py      # Console/log output display
│   ├── buttons.py       # Custom styled buttons
│   └── status_bar.py    # Footer/status info
└── assets/              # Image/icon storage
    ├── README.md
    └── icon.png
```

## Module Responsibilities

### `main.py` - Entry Point
- Main `CleanHouseUI` class that orchestrates all components
- Maintains compatibility with `brain.py` integration
- Provides the `ignite_passion()` method for core functionality
- Handles UI initialization and periodic updates

### `layout.py` - Visual Components
- All window layout, geometry, and styling
- Tab creation and organization
- Widget placement and configuration
- Visual state management (colors, fonts, etc.)

### `events.py` - User Interactions
- All UI event bindings and handlers
- Window management (close, resize, etc.)
- User input processing
- Event delegation to appropriate modules

### `hooks.py` - Business Logic Bridge
- Actions that trigger CleanHouse core functionality
- Integration with `corefiles` modules
- Data processing and result handling
- Status updates and progress tracking

### `widgets/` - Custom Components
- Reusable UI components
- Enhanced styling and behavior
- Specialized widgets for specific functions

## Usage

### Running the UI

The modular UI can be launched in several ways:

1. **Direct execution:**
   ```bash
   python -m ui.main
   ```

2. **Using the launch script:**
   ```bash
   python launch_ui.py
   ```

3. **From Python code:**
   ```python
   from ui import CleanHouseUI
   app = CleanHouseUI()
   app.mainloop()
   ```

### Brain.py Compatibility

The modular UI maintains full compatibility with the existing `brain.py` integration:

```python
from ui import CleanHouseUI

# Create UI instance
app = CleanHouseUI()

# Use the ignite_passion method (same as before)
results = app.ignite_passion(target_dir=Path("/some/directory"), threshold=3, dry_run=True)
```

## Benefits of Modular Architecture

1. **Maintainability**: Each module has a single responsibility
2. **Readability**: Code is organized logically and easy to navigate
3. **Extensibility**: Easy to add new features or modify existing ones
4. **Testing**: Individual modules can be tested in isolation
5. **Reusability**: Widgets and components can be reused across the application

## Development Guidelines

### Adding New Features

1. **UI Layout**: Add visual components to `layout.py`
2. **User Interactions**: Add event handlers to `events.py`
3. **Business Logic**: Add core functionality hooks to `hooks.py`
4. **Custom Widgets**: Create new widgets in the `widgets/` folder

### Code Organization

- Keep layout code in `layout.py`
- Keep event handling in `events.py`
- Keep business logic integration in `hooks.py`
- Use clear, descriptive function names
- Add comments for complex functionality

### Import Structure

- Modules import from each other using relative imports
- Core functionality is imported from `corefiles`
- External dependencies are imported at the module level

## Migration from Original UI

The original `ui.py` file has been completely refactored into this modular structure. All functionality has been preserved, but the code is now:

- More organized and maintainable
- Easier to extend and modify
- Better separated by concern
- More testable and debuggable

## Dependencies

The modular UI requires the same dependencies as the original UI:

- `tkinter` (built-in with Python)
- `matplotlib` for graphs and charts
- `psutil` for system monitoring
- All `corefiles` modules
- Cloud service dependencies (Google, Dropbox, etc.)

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure all dependencies are installed
2. **Tkinter Issues**: Use system Python instead of virtual environment
3. **Module Not Found**: Check that the project root is in Python path

### Testing

Use the provided test scripts to verify functionality:

```bash
# Test imports only
python test_ui_imports.py

# Test full UI (requires tkinter)
python test_ui.py
```
