# UI Assets

This directory contains assets for the CleanHouse UI, including:

- `icon.png` - Application icon
- `images/` - Image assets for the UI
- `icons/` - Icon assets for buttons and controls

## Usage

Assets in this directory can be referenced in the UI code using relative paths from the ui module:

```python
icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'icon.png')
```
