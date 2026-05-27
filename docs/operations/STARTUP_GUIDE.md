# 🚀 CleanHouse Startup Guide

This guide helps you run CleanHouse with or without optional dependencies.

## 🏗️ Architecture Overview

CleanHouse has **modular components** that can work independently:

| Component | File | Dependencies | Purpose |
|-----------|------|-------------|---------|
| **🧠 Zaelith CLI** | `Zaelith/brain.py` | None (stdlib only) | Standalone lie detector |
| **🏠 Core CLI** | `corefiles/brain.py` | Minimal | Basic monitoring + launcher |
| **🖥️ Full GUI** | `ui.py` | tkinter, matplotlib | Complete interface |
| **⚡ Service Layer** | `corefiles/zaelith_service.py` | None | Integration API |

## 📦 Dependency Levels

### Level 1: Core Functionality (No extra deps)
```bash
# Basic CLI monitoring and lie detection
python3 Zaelith/brain.py              # Standalone lie detector
python3 corefiles/brain.py --monitor  # Basic file monitoring
python3 corefiles/brain.py --help     # See all options

# 💡 Press Ctrl+C to terminate CleanHouse at any time
```

### Level 2: Service Integration (No GUI deps)
```bash
# Programmatic analysis without GUI
python3 examples/zaelith_usage.py                  # Service examples
python3 tools/manual/zaelith_integration_probe.py  # Integration probe
```

### Level 3: Full GUI Experience (All features)
```bash
# Complete GUI with all features
python3 corefiles/brain.py            # Launch GUI (recommended)
python3 ui.py                         # Direct GUI launch

# 💡 Press Ctrl+C to terminate CleanHouse GUI at any time
```

## 🛠️ Installation Options

### Option 1: Minimal Installation (Core Only)
```bash
# No extra dependencies needed! Uses Python stdlib only
cd CleanHouse
python3 Zaelith/brain.py              # Works immediately
python3 corefiles/brain.py --monitor  # Works immediately
```

### Option 2: Full Installation (All Features)
```bash
# Install GUI dependencies
pip install matplotlib tkinter
# or install all dependencies
pip install -r requirements.txt

# Then run full GUI
python3 launch_cleanhouse.py
```

### Option 3: Selective Installation
```bash
# Just matplotlib for graphs
pip install matplotlib

# Just tkinter for basic GUI (usually pre-installed)
# tkinter comes with most Python installations

# Test what's available
python3 launch_cleanhouse.py  # Shows dependency status
```

## 🎯 Quick Start (No Installation)

**Want to try CleanHouse immediately with zero setup?**

```bash
cd CleanHouse

# 1. Test standalone lie detection
python3 Zaelith/brain.py
# Enter a prompt and response, type 'run' to analyze

# 2. Test CLI monitoring
python3 corefiles/brain.py --monitor .
# Monitors current directory for changes

# 3. Test service integration
python3 examples/zaelith_usage.py
# Shows programmatic usage examples
```

## 🔧 Troubleshooting

### "ModuleNotFoundError: No module named 'matplotlib'"
**Solution**: You're trying to run GUI features without GUI dependencies.

**Options**:
- Install matplotlib: `pip install matplotlib`
- Use CLI only: `python3 corefiles/brain.py --monitor`
- Use standalone Zaelith: `python3 Zaelith/brain.py`

### "ModuleNotFoundError: No module named '_tkinter'"
**Solution**: tkinter not available.

**Options**:
- Install tkinter: `pip install tk` (or use system package manager)
- Use CLI only: `python3 corefiles/brain.py --monitor`
- Use service API: `python3 examples/zaelith_usage.py`

### Import errors from corefiles
**Solution**: Path issues or missing modules.

**Fix**:
```bash
# Run from the CleanHouse root directory
cd CleanHouse
python3 corefiles/brain.py --help
```

### GUI won't start
**Solution**: Dependency or display issues.

**Debug**:
```bash
# Test dependencies
python3 launch_cleanhouse.py  # Shows detailed error info

# Fallback to CLI
python3 corefiles/brain.py --monitor /path/to/monitor
```

## 📂 File Organization

```
CleanHouse/
├── 📁 Zaelith/                   # Standalone lie detection
│   ├── brain.py                  # ✅ No dependencies
│   └── detector.py               # ✅ No dependencies
├── 📁 corefiles/                 # CleanHouse core
│   ├── brain.py                  # ✅ Minimal dependencies
│   ├── config.py                 # ✅ No extra dependencies
│   └── zaelith_service.py        # ✅ No extra dependencies
├── ui.py                         # ⚠️ Requires tkinter + matplotlib
├── launch_cleanhouse.py          # 🚀 Smart launcher with checks
├── examples/zaelith_usage.py     # ✅ No GUI dependencies
└── requirements.txt              # 📦 Optional dependencies
```

## 💡 Recommended Workflow

1. **Start Simple**: Try `python3 Zaelith/brain.py` first
2. **Test Integration**: Run `python3 examples/zaelith_usage.py`
3. **Add GUI**: Install matplotlib and run `python3 launch_cleanhouse.py`
4. **Full Setup**: Install all requirements for complete features

## 🎊 Success Indicators

- ✅ **CLI Working**: `python3 corefiles/brain.py --help` shows usage
- ✅ **Lie Detection Working**: `python3 Zaelith/brain.py` accepts input
- ✅ **Service Working**: `python3 examples/zaelith_usage.py` shows analysis
- ✅ **GUI Working**: `python3 launch_cleanhouse.py` opens window
- ✅ **Integration Working**: Lie Detection tab appears in GUI

The modular design means you can start using CleanHouse immediately, then add features as you install dependencies!
