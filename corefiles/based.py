# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - based.py
#  K.I.S.S.
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────────── Imports ──────────────────────────────────╮
from .integrity import generate_baseline
from . import config
import sys
from pathlib import Path
# ───────────────────────────────────────────────────────────────────────────╯

# ╭───────────────────────────── Launcher ───────────────────────────────────╮
if __name__ == "__main__":
    print("🧾 Generating baseline...")

    # Allow user to specify directory as argument, or use config.BASE_DIR
    target_dir = config.BASE_DIR
    if target_dir is None:
        if len(sys.argv) > 1:
            target_dir = Path(sys.argv[1])
        else:
            print("❌ BASE_DIR is not set. Please provide a directory as an argument.")
            sys.exit(1)
    else:
        target_dir = Path(target_dir)

    # Generate baseline directly to the centralized location
    generate_baseline(target_dir)
    print(f"✅ Baseline created at: {config.INTEGRITY_BASELINE_FILE}")
# ───────────────────────────────────────────────────────────────────────────╯