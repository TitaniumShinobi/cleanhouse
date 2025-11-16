"""
Terminal Widget

A custom terminal/console widget for displaying log output and system messages.
"""

import tkinter as tk
from tkinter import ttk
import queue
from datetime import datetime


class TerminalWidget(tk.Text):
    """
    A custom terminal widget for displaying log output and system messages.
    """
    
    def __init__(self, parent, **kwargs):
        # Set default options
        default_options = {
            'font': ('Consolas', 10),
            'bg': '#222',
            'fg': '#eee',
            'wrap': 'none',
            'padx': 5,
            'pady': 5,
            'state': 'disabled'
        }
        default_options.update(kwargs)
        
        super().__init__(parent, **default_options)
        
        # Configure tags for different log levels
        self.tag_configure("INFO", foreground="#4caf50")
        self.tag_configure("WARNING", foreground="#ffa000")
        self.tag_configure("ERROR", foreground="#e53935")
        self.tag_configure("CRITICAL", foreground="#e53935", font=("Consolas", 10, "bold"))
        self.tag_configure("timestamp", foreground="#888")
        self.tag_configure("summary", foreground="#ffa000", font=("Consolas", 9, "italic"))
        
        # Initialize log queue
        self.log_queue = queue.Queue()
        
        # Bind events
        self.bind('<Key>', self._on_key_press)
    
    def _on_key_press(self, event):
        """Handle key press events."""
        # Disable editing by default
        return "break"
    
    def append_log(self, message, level="INFO", timestamp=None):
        """Append a log message to the terminal."""
        if timestamp is None:
            timestamp = datetime.now()
        
        # Enable editing
        self.config(state='normal')
        
        # Insert timestamp
        time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        self.insert(tk.END, f"[{time_str}] ", "timestamp")
        
        # Insert level with appropriate tag
        self.insert(tk.END, f"{level} ", level)
        
        # Insert message
        self.insert(tk.END, f"{message}\n")
        
        # Disable editing
        self.config(state='disabled')
        
        # Scroll to bottom
        self.see(tk.END)
    
    def clear(self):
        """Clear the terminal content."""
        self.config(state='normal')
        self.delete(1.0, tk.END)
        self.config(state='disabled')
    
    def get_content(self):
        """Get the current content of the terminal."""
        return self.get(1.0, tk.END)
    
    def set_content(self, content):
        """Set the content of the terminal."""
        self.config(state='normal')
        self.delete(1.0, tk.END)
        self.insert(1.0, content)
        self.config(state='disabled')
        self.see(tk.END)
