"""
Custom Button Widgets

Custom styled button components for the CleanHouse UI.
"""

import tkinter as tk
from tkinter import ttk


class CustomButton(tk.Button):
    """
    A custom button widget with enhanced styling and hover effects.
    """
    
    def __init__(self, parent, **kwargs):
        # Set default options
        default_options = {
            'font': ('Segoe UI', 10),
            'relief': 'flat',
            'bd': 0,
            'cursor': 'hand2',
            'activebackground': None,
            'activeforeground': None
        }
        default_options.update(kwargs)
        
        super().__init__(parent, **default_options)
        
        # Bind hover effects
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)
        
        # Store original colors
        self.original_bg = self.cget('bg')
        self.original_fg = self.cget('fg')
    
    def _on_enter(self, event):
        """Handle mouse enter event."""
        # Slightly darken the background
        if self.original_bg:
            try:
                # Convert hex to RGB and darken
                if self.original_bg.startswith('#'):
                    rgb = tuple(int(self.original_bg[i:i+2], 16) for i in (1, 3, 5))
                    darkened = tuple(max(0, c - 20) for c in rgb)
                    darkened_hex = f"#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}"
                    self.config(bg=darkened_hex)
            except:
                pass
    
    def _on_leave(self, event):
        """Handle mouse leave event."""
        # Restore original colors
        self.config(bg=self.original_bg, fg=self.original_fg)
    
    def _on_click(self, event):
        """Handle click event."""
        # Brief visual feedback
        original_bg = self.cget('bg')
        try:
            if original_bg.startswith('#'):
                rgb = tuple(int(original_bg[i:i+2], 16) for i in (1, 3, 5))
                brightened = tuple(min(255, c + 30) for c in rgb)
                brightened_hex = f"#{brightened[0]:02x}{brightened[1]:02x}{brightened[2]:02x}"
                self.config(bg=brightened_hex)
                self.after(100, lambda: self.config(bg=original_bg))
        except:
            pass


class AccentButton(CustomButton):
    """
    An accent button with special styling for important actions.
    """
    
    def __init__(self, parent, **kwargs):
        # Set accent button defaults
        accent_defaults = {
            'bg': '#1976d2',
            'fg': 'white',
            'font': ('Segoe UI', 11, 'bold'),
            'relief': 'raised',
            'bd': 1
        }
        accent_defaults.update(kwargs)
        
        super().__init__(parent, **accent_defaults)


class DangerButton(CustomButton):
    """
    A danger button with red styling for destructive actions.
    """
    
    def __init__(self, parent, **kwargs):
        # Set danger button defaults
        danger_defaults = {
            'bg': '#e53935',
            'fg': 'white',
            'font': ('Segoe UI', 11, 'bold'),
            'relief': 'raised',
            'bd': 1
        }
        danger_defaults.update(kwargs)
        
        super().__init__(parent, **danger_defaults)


class SuccessButton(CustomButton):
    """
    A success button with green styling for positive actions.
    """
    
    def __init__(self, parent, **kwargs):
        # Set success button defaults
        success_defaults = {
            'bg': '#4caf50',
            'fg': 'white',
            'font': ('Segoe UI', 11, 'bold'),
            'relief': 'raised',
            'bd': 1
        }
        success_defaults.update(kwargs)
        
        super().__init__(parent, **success_defaults)
