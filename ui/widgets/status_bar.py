"""
Status Bar Widget

A custom status bar widget for displaying system status and information.
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime


class StatusBar(tk.Frame):
    """
    A custom status bar widget for displaying system status and information.
    """
    
    def __init__(self, parent, **kwargs):
        # Set default options
        default_options = {
            'bg': '#f0f0f0',
            'relief': 'sunken',
            'bd': 1,
            'height': 25
        }
        default_options.update(kwargs)
        
        super().__init__(parent, **default_options)
        
        # Create status elements
        self._create_status_elements()
        
        # Start periodic updates
        self._update_time()
    
    def _create_status_elements(self):
        """Create the status bar elements."""
        # Left side - Status message
        self.status_frame = tk.Frame(self, bg=self.cget('bg'))
        self.status_frame.pack(side='left', fill='x', expand=True, padx=5, pady=2)
        
        self.status_label = tk.Label(
            self.status_frame,
            text="Ready",
            font=('Segoe UI', 9),
            bg=self.cget('bg'),
            fg='#333'
        )
        self.status_label.pack(side='left')
        
        # Right side - Time and other info
        self.info_frame = tk.Frame(self, bg=self.cget('bg'))
        self.info_frame.pack(side='right', padx=5, pady=2)
        
        self.time_label = tk.Label(
            self.info_frame,
            text="",
            font=('Segoe UI', 9),
            bg=self.cget('bg'),
            fg='#666'
        )
        self.time_label.pack(side='right')
        
        # Separator
        separator = tk.Frame(self.info_frame, width=1, bg='#ccc')
        separator.pack(side='right', fill='y', padx=5)
        
        # Progress bar (hidden by default)
        self.progress = ttk.Progressbar(
            self.info_frame,
            mode='indeterminate',
            length=100
        )
        self.progress.pack(side='right', padx=5)
        self.progress.pack_forget()  # Hide by default
    
    def set_status(self, message, color='#333'):
        """Set the status message."""
        self.status_label.config(text=message, fg=color)
    
    def show_progress(self):
        """Show the progress bar."""
        self.progress.pack(side='right', padx=5)
        self.progress.start()
    
    def hide_progress(self):
        """Hide the progress bar."""
        self.progress.stop()
        self.progress.pack_forget()
    
    def set_progress(self, value):
        """Set progress bar value (0-100)."""
        self.progress.config(mode='determinate', value=value)
    
    def _update_time(self):
        """Update the time display."""
        current_time = datetime.now().strftime('%H:%M:%S')
        self.time_label.config(text=current_time)
        
        # Schedule next update
        self.after(1000, self._update_time)
    
    def add_info(self, text, color='#666'):
        """Add additional information to the status bar."""
        info_label = tk.Label(
            self.info_frame,
            text=text,
            font=('Segoe UI', 9),
            bg=self.cget('bg'),
            fg=color
        )
        info_label.pack(side='right', padx=5)
        
        # Add separator
        separator = tk.Frame(self.info_frame, width=1, bg='#ccc')
        separator.pack(side='right', fill='y', padx=2)
        
        return info_label
