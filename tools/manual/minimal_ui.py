#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - Minimal UI (No matplotlib required)
#  Devon • 2025-10-20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import os
from pathlib import Path
import logging
from datetime import datetime
import json

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler()]
)

class MinimalCleanHouseUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CleanHouse - Minimal Interface")
        self.geometry("800x600")
        self.configure(bg="#f4f6fa")

        # Initialize variables
        self.status_var = tk.StringVar(value="Ready")
        self.target_dir = tk.StringVar(value=str(Path.home()))

        self.create_interface()

    def create_interface(self):
        """Create the minimal interface."""
        # Main title
        title_frame = tk.Frame(self, bg="#f4f6fa")
        title_frame.pack(fill='x', pady=10)

        tk.Label(title_frame, text="🏠 CleanHouse",
                font=("Arial", 24, "bold"), bg="#f4f6fa").pack()
        tk.Label(title_frame, text="Minimal Interface (No matplotlib required)",
                font=("Arial", 12), bg="#f4f6fa", fg="#666").pack()

        # Status
        status_frame = tk.Frame(self, bg="#f4f6fa")
        status_frame.pack(fill='x', pady=10)

        tk.Label(status_frame, text="Status:", font=("Arial", 14, "bold"),
                bg="#f4f6fa").pack(side='left', padx=10)
        tk.Label(status_frame, textvariable=self.status_var,
                font=("Arial", 14), bg="#f4f6fa", fg="green").pack(side='left')

        # Directory selection
        dir_frame = ttk.LabelFrame(self, text="Target Directory", padding=10)
        dir_frame.pack(fill='x', padx=20, pady=10)

        ttk.Label(dir_frame, text="Directory to monitor:").pack(anchor='w')

        dir_input_frame = ttk.Frame(dir_frame)
        dir_input_frame.pack(fill='x', pady=5)

        self.dir_entry = ttk.Entry(dir_input_frame, textvariable=self.target_dir, width=60)
        self.dir_entry.pack(side='left', fill='x', expand=True, padx=(0, 5))

        ttk.Button(dir_input_frame, text="Browse",
                  command=self.browse_directory).pack(side='right')

        # Actions
        actions_frame = ttk.LabelFrame(self, text="Actions", padding=10)
        actions_frame.pack(fill='x', padx=20, pady=10)

        button_frame = ttk.Frame(actions_frame)
        button_frame.pack(fill='x')

        ttk.Button(button_frame, text="Scan Directory",
                  command=self.scan_directory).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Monitor Directory",
                  command=self.monitor_directory).pack(side='left', padx=5)
        ttk.Button(button_frame, text="View Logs",
                  command=self.view_logs).pack(side='left', padx=5)

        # Results area
        results_frame = ttk.LabelFrame(self, text="Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=20, pady=10)

        # Results text with scrollbar
        text_frame = ttk.Frame(results_frame)
        text_frame.pack(fill='both', expand=True)

        self.results_text = tk.Text(text_frame, wrap=tk.WORD, height=15)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=scrollbar.set)

        self.results_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Add initial message
        self.log_message("CleanHouse initialized. Select a directory to begin.")

    def browse_directory(self):
        """Browse for target directory."""
        directory = filedialog.askdirectory(title="Select Directory to Monitor")
        if directory:
            self.target_dir.set(directory)
            self.log_message(f"Selected directory: {directory}")

    def scan_directory(self):
        """Scan the selected directory."""
        target = Path(self.target_dir.get())
        if not target.exists():
            messagebox.showerror("Error", "Directory does not exist")
            return

        self.status_var.set("Scanning...")
        self.log_message(f"\n🔍 Scanning {target}...")

        try:
            # Simple file scan
            python_files = list(target.rglob("*.py"))
            json_files = list(target.rglob("*.json"))
            txt_files = list(target.rglob("*.txt"))

            total_files = len(python_files) + len(json_files) + len(txt_files)

            self.log_message(f"Found {total_files} files:")
            self.log_message(f"  • Python files: {len(python_files)}")
            self.log_message(f"  • JSON files: {len(json_files)}")
            self.log_message(f"  • Text files: {len(txt_files)}")

            # Simple security check
            suspicious_patterns = ['eval(', 'exec(', 'os.system', 'subprocess']
            issues_found = 0

            for py_file in python_files[:10]:  # Check first 10 files
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        for pattern in suspicious_patterns:
                            if pattern in content:
                                self.log_message(f"⚠️  Found '{pattern}' in {py_file}")
                                issues_found += 1
                except Exception as e:
                    continue

            if issues_found == 0:
                self.log_message("✅ No obvious security issues found")
            else:
                self.log_message(f"⚠️  Found {issues_found} potential security issues")

            self.status_var.set("Scan Complete")

        except Exception as e:
            self.log_message(f"❌ Scan failed: {str(e)}")
            self.status_var.set("Scan Failed")

    def monitor_directory(self):
        """Start monitoring the directory."""
        target = Path(self.target_dir.get())
        if not target.exists():
            messagebox.showerror("Error", "Directory does not exist")
            return

        self.status_var.set("Monitoring...")
        self.log_message(f"\n👁️  Starting monitoring of {target}")
        self.log_message("Monitoring will check for file changes every 30 seconds...")

        # Start monitoring in background thread
        def monitor_loop():
            file_count = len(list(target.rglob("*")))
            for i in range(10):  # Monitor for 10 cycles (5 minutes)
                if not hasattr(self, 'monitoring') or not self.monitoring:
                    break

                current_count = len(list(target.rglob("*")))
                timestamp = datetime.now().strftime("%H:%M:%S")

                if current_count != file_count:
                    self.log_message(f"[{timestamp}] File count changed: {file_count} → {current_count}")
                    file_count = current_count
                else:
                    self.log_message(f"[{timestamp}] No changes detected ({current_count} files)")

                time.sleep(30)  # Wait 30 seconds

            self.log_message("Monitoring stopped.")
            self.status_var.set("Ready")

        self.monitoring = True
        threading.Thread(target=monitor_loop, daemon=True).start()

    def view_logs(self):
        """View application logs."""
        self.log_message("\n📋 Application Logs:")
        self.log_message(f"Started at: {datetime.now()}")
        self.log_message(f"Target directory: {self.target_dir.get()}")
        self.log_message(f"Current status: {self.status_var.get()}")

        # Show system info
        self.log_message(f"Python executable: {Path(__file__).parent}")
        self.log_message(f"Working directory: {os.getcwd()}")

    def log_message(self, message):
        """Add a message to the results area."""
        self.results_text.insert(tk.END, f"{message}\n")
        self.results_text.see(tk.END)
        self.update_idletasks()

def main():
    """Main function."""
    print("🏠 Starting CleanHouse Minimal Interface...")

    try:
        app = MinimalCleanHouseUI()
        print("✅ CleanHouse GUI started successfully!")
        app.mainloop()
    except Exception as e:
        print(f"❌ Failed to start GUI: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()