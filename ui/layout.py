"""
UI Layout Module

Handles all window layout, geometry, styling, and visual components.
This module is responsible for creating and organizing UI elements.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import json
import queue
from pathlib import Path
from datetime import datetime

# Optional matplotlib import (for data visualization)
try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    FigureCanvasTkAgg = None

from corefiles import config
from corefiles.error_handler import CustomLogHandler
from .widgets.terminal import TerminalWidget
from .widgets.buttons import CustomButton
from .widgets.status_bar import StatusBar


class UILayout:
    """
    Handles all UI layout and visual components.
    """
    
    def __init__(self, parent):
        self.parent = parent
        self.style = None
        self.notebook = None
        
        # Initialize state variables
        self._init_state_variables()
        
        # Initialize managers
        self._init_managers()
        
        # Initialize widgets
        self._init_widgets()
    
    def _init_state_variables(self):
        """Initialize UI state variables."""
        # Status variables
        self.status_var = tk.StringVar(value="Not Scanned")
        self.status_color = "#4caf50"
        self.scan_progress = tk.DoubleVar(value=0)
        self.last_scan = tk.StringVar(value="Never")
        self.files_scanned = tk.IntVar(value=0)
        self.issues_found = tk.IntVar(value=0)
        self.scan_running = False
        self.monitoring = False
        self.monitor_thread = None
        self.target_dir = tk.StringVar(value=str(config.BASE_DIR))
        
        # Directory statistics
        self.dir_size = tk.StringVar(value="0 MB")
        self.file_count = tk.IntVar(value=0)
        self.dir_status = tk.StringVar(value="Not Monitored")
        
        # Directory history
        self.directory_history = []
        self.load_directory_history()
        
        # Cloud settings
        self.gdrive_var = tk.BooleanVar(value=config.CLOUD_SERVICES.get('gdrive', False))
        self.dropbox_var = tk.BooleanVar(value=config.CLOUD_SERVICES.get('dropbox', False))
        self.onedrive_var = tk.BooleanVar(value=config.CLOUD_SERVICES.get('onedrive', False))
        self.github_var = tk.BooleanVar(value=config.CLOUD_SERVICES.get('github', False))
        self.backup_interval = tk.StringVar(value=str(config.CLOUD_BACKUP_INTERVAL // 3600))
        self.github_repo = tk.StringVar(value=config.GITHUB_REPO)
        
        # Log filtering
        self.level_var = tk.StringVar(value="ALL")
        self.filter_var = tk.StringVar()
        
        # Settings
        self.interval_entry = None
        self.mode_combo = None
        
        # Zaelith variables
        self.prompt_text = None
        self.response_text = None
        self.analyze_btn = None
        self.summary_text = None
        self.detailed_text = None
        self.history_listbox = None
        self.zaelith_status_label = None
    
    def _init_managers(self):
        """Initialize service managers."""
        try:
            from corefiles.cloud import CloudStorageManager
            from corefiles.notifications import NotificationManager
            from corefiles.zaelith_service import get_zaelith_service
            
            self.cloud_manager = CloudStorageManager()
        except Exception as e:
            print(f"Failed to initialize cloud manager: {e}")
            self.cloud_manager = None
            
        try:
            self.notification_manager = NotificationManager()
        except Exception as e:
            print(f"Failed to initialize notification manager: {e}")
            self.notification_manager = None
            
        try:
            self.zaelith_service = get_zaelith_service()
            self.zaelith_available = True
        except Exception as e:
            print(f"Failed to initialize Zaelith service: {e}")
            self.zaelith_service = None
            self.zaelith_available = False
    
    def _init_widgets(self):
        """Initialize custom widgets."""
        self.terminal_widget = TerminalWidget(self.parent)
        self.status_bar = StatusBar(self.parent)
    
    def create_menu(self):
        """Create the main menu bar."""
        menubar = tk.Menu(self.parent)
        
        # File menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Export Logs", command=self.parent.events.export_logs)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.parent.quit)
        menubar.add_cascade(label="File", menu=filemenu)
        
        # Service menu
        servicemenu = tk.Menu(menubar, tearoff=0)
        servicemenu.add_command(label="Install Service", command=self.parent.events.install_service)
        servicemenu.add_command(label="Remove Service", command=self.parent.events.remove_service)
        menubar.add_cascade(label="Service", menu=servicemenu)
        
        # Cloud menu
        cloudmenu = tk.Menu(menubar, tearoff=0)
        cloudmenu.add_command(label="Upload Baseline", command=self.parent.events.upload_baseline)
        cloudmenu.add_command(label="Configure Cloud Services", command=self.parent.events.configure_cloud)
        menubar.add_cascade(label="Cloud", menu=cloudmenu)
        
        # Help menu
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About", command=self.parent.events.show_about)
        menubar.add_cascade(label="Help", menu=helpmenu)
        
        self.parent.config(menu=menubar)
    
    def create_tabs(self):
        """Create the main tabbed interface."""
        # Configure style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TNotebook.Tab', font=('Segoe UI', 11, 'bold'))
        self.style.configure('TFrame', background="#f4f6fa")
        
        # Create notebook
        self.notebook = ttk.Notebook(self.parent)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create tabs based on user role
        self._create_dashboard_tab()
        self._create_results_tab()
        self._create_logs_tab()
        self._create_settings_tab()
        self._create_cloud_tab()
        self._create_monitoring_tab()
        
        # Developer-only tabs
        if self._can_access_module("lie_detection"):
            self._create_lie_detection_tab()
        
        if self._can_access_module("zaelith"):
            self._create_zaelith_tab()
    
    def _can_access_module(self, module_name: str) -> bool:
        """Check if current user can access a specific module."""
        # Get user manager from parent if available
        if hasattr(self.parent, 'user_manager') and self.parent.user_manager:
            return self.parent.user_manager.can_access_module(module_name)
        
        # Default to allowing access if no user manager
        return True
    
    def _create_dashboard_tab(self):
        """Create the dashboard tab."""
        dashboard = ttk.Frame(self.notebook)
        self.notebook.add(dashboard, text="Dashboard")
        
        # Status Panel
        status_frame = tk.Frame(dashboard, bg="#f4f6fa")
        status_frame.pack(fill='x', pady=10, padx=10)
        tk.Label(status_frame, text="Status:", font=("Segoe UI", 16, "bold"), bg="#f4f6fa").pack(side='left', padx=(10,0))
        self.status_label = tk.Label(status_frame, textvariable=self.status_var, font=("Segoe UI", 16, "bold"), bg="#f4f6fa", fg=self.status_color)
        self.status_label.pack(side='left', padx=10)
        
        # Target Directory Selection
        self._create_directory_selection(dashboard)
        
        # Scan Controls
        self._create_scan_controls(dashboard)
        
        # Quick Stats
        self._create_quick_stats(dashboard)
    
    def _create_directory_selection(self, parent):
        """Create directory selection interface."""
        target_frame = tk.Frame(parent, bg="#f4f6fa")
        target_frame.pack(fill='x', pady=(10, 0), padx=10)
        
        # Label above the button to show the selected path
        self.target_path_label = tk.Label(target_frame, text="No directory selected", font=("Segoe UI", 10, "italic"), bg="#f4f6fa", fg="#555")
        self.target_path_label.pack(anchor='w', padx=(30,0), pady=(0,2))
        
        # Row with label and button
        row_frame = tk.Frame(target_frame, bg="#f4f6fa")
        row_frame.pack(fill='x')
        tk.Label(row_frame, text="Target Directory:", font=("Segoe UI", 10), bg="#f4f6fa").pack(side='left', padx=(30,0))
        
        # Add directory history dropdown
        self.dir_history_var = tk.StringVar()
        self.dir_history_combo = ttk.Combobox(row_frame, textvariable=self.dir_history_var, 
                                            values=self.directory_history, width=40)
        self.dir_history_combo.pack(side='left', padx=5)
        self.dir_history_combo.bind('<<ComboboxSelected>>', self.parent.events.on_directory_history_select)
        
        browse_btn = CustomButton(row_frame, text="Browse...", font=("Segoe UI", 10), command=self.parent.events.browse_target)
        browse_btn.pack(side='left', padx=5)
        
        # Add a tooltip to explain the directory selection
        self.create_tooltip(browse_btn, "Select a directory to monitor for integrity changes")
        
        # Directory statistics frame
        stats_frame = tk.Frame(target_frame, bg="#f4f6fa")
        stats_frame.pack(fill='x', padx=(30,0), pady=5)
        
        # Size and file count
        tk.Label(stats_frame, text="Size:", font=("Segoe UI", 9), bg="#f4f6fa").pack(side='left', padx=(0,5))
        tk.Label(stats_frame, textvariable=self.dir_size, font=("Segoe UI", 9, "bold"), bg="#f4f6fa").pack(side='left', padx=(0,15))
        
        tk.Label(stats_frame, text="Files:", font=("Segoe UI", 9), bg="#f4f6fa").pack(side='left', padx=(0,5))
        tk.Label(stats_frame, textvariable=self.file_count, font=("Segoe UI", 9, "bold"), bg="#f4f6fa").pack(side='left', padx=(0,15))
        
        # Directory status
        tk.Label(stats_frame, text="Status:", font=("Segoe UI", 9), bg="#f4f6fa").pack(side='left', padx=(0,5))
        tk.Label(stats_frame, textvariable=self.dir_status, font=("Segoe UI", 9, "bold"), bg="#f4f6fa").pack(side='left')
    
    def _create_scan_controls(self, parent):
        """Create scan control interface."""
        scan_frame = tk.Frame(parent, bg="#f4f6fa")
        scan_frame.pack(fill='x', pady=10, padx=10)
        
        self.scan_btn = CustomButton(scan_frame, text="Start Scan", font=("Segoe UI", 12), 
                                   bg="#1976d2", fg="white", command=self.parent.events.toggle_scan)
        self.scan_btn.pack(side='left', padx=10)
        
        self.progress = ttk.Progressbar(scan_frame, variable=self.scan_progress, maximum=100, length=300)
        self.progress.pack(side='left', padx=10)
        
        tk.Label(scan_frame, text="Last Scan:", font=("Segoe UI", 10), bg="#f4f6fa").pack(side='left', padx=(30,0))
        tk.Label(scan_frame, textvariable=self.last_scan, font=("Segoe UI", 10), bg="#f4f6fa").pack(side='left', padx=5)
        
        # Monitoring Controls
        self.monitor_btn = CustomButton(scan_frame, text="Start Monitoring", font=("Segoe UI", 12), 
                                      bg="#388e3c", fg="white", command=self.parent.events.toggle_monitoring)
        self.monitor_btn.pack(side='left', padx=10)
        
        # Initialize Baseline Button
        self.init_baseline_btn = CustomButton(scan_frame, text="Initialize Baseline", font=("Segoe UI", 12), 
                                            bg="#607d8b", fg="white", command=self.parent.events.init_baseline)
        self.init_baseline_btn.pack(side='left', padx=10)
    
    def _create_quick_stats(self, parent):
        """Create quick statistics display."""
        stats_frame = tk.Frame(parent, bg="#f4f6fa")
        stats_frame.pack(fill='x', pady=10, padx=10)
        tk.Label(stats_frame, text="Files Scanned:", font=("Segoe UI", 12), bg="#f4f6fa").pack(side='left', padx=(10,0))
        tk.Label(stats_frame, textvariable=self.files_scanned, font=("Segoe UI", 12, "bold"), bg="#f4f6fa").pack(side='left', padx=5)
        tk.Label(stats_frame, text="Issues Found:", font=("Segoe UI", 12), bg="#f4f6fa").pack(side='left', padx=(30,0))
        tk.Label(stats_frame, textvariable=self.issues_found, font=("Segoe UI", 12, "bold"), bg="#f4f6fa", fg="#e53935").pack(side='left', padx=5)
    
    def _create_results_tab(self):
        """Create the scan results tab."""
        results = ttk.Frame(self.notebook)
        self.notebook.add(results, text="Scan Results")
        
        self.results_list = tk.Listbox(results, font=("Segoe UI", 11), bg="#fff", fg="#333")
        self.results_list.pack(fill='both', expand=True, padx=10, pady=10)
    
    def _create_logs_tab(self):
        """Create the logs tab."""
        logs = ttk.Frame(self.notebook)
        self.notebook.add(logs, text="Logs")
        
        # Create main frame
        main_frame = ttk.Frame(logs, padding=10)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create filter frame
        filter_frame = ttk.Frame(main_frame, padding=5)
        filter_frame.pack(fill='x', pady=(0, 5))
        
        # Level filter
        ttk.Label(filter_frame, text="Level:").pack(side='left', padx=(0, 5))
        level_combo = ttk.Combobox(filter_frame, textvariable=self.level_var, 
                                 values=["ALL", "INFO", "WARNING", "ERROR"],
                                 state="readonly", width=10)
        level_combo.pack(side='left', padx=(0, 10))
        level_combo.bind('<<ComboboxSelected>>', self.update_log_display)
        
        # Search filter
        ttk.Label(filter_frame, text="Search:").pack(side='left', padx=(0, 5))
        search_entry = ttk.Entry(filter_frame, textvariable=self.filter_var, width=30)
        search_entry.pack(side='left', padx=(0, 10))
        search_entry.bind('<KeyRelease>', self.update_log_display)
        
        # Clear filters button
        ttk.Button(filter_frame, text="Clear Filters", 
                  command=self.clear_log_filters).pack(side='left', padx=5)
        
        # Create log display with scrollbar
        log_frame = ttk.Frame(main_frame, padding=5)
        log_frame.pack(fill='both', expand=True)
        
        # Create text widget with custom tags
        self.logs_text = tk.Text(log_frame, font=("Consolas", 10), bg="#222", fg="#eee",
                                wrap='none', padx=5, pady=5)
        self.logs_text.pack(side='left', fill='both', expand=True, padx=5, pady=5)
        
        # Configure tags for different log levels
        self.logs_text.tag_configure("INFO", foreground="#4caf50")
        self.logs_text.tag_configure("WARNING", foreground="#ffa000")
        self.logs_text.tag_configure("ERROR", foreground="#e53935")
        self.logs_text.tag_configure("timestamp", foreground="#888")
        self.logs_text.tag_configure("summary", foreground="#ffa000", font=("Consolas", 9, "italic"))
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.logs_text.yview)
        scrollbar.pack(side='right', fill='y')
        self.logs_text.configure(yscrollcommand=scrollbar.set)
        
        # Add horizontal scrollbar
        h_scrollbar = ttk.Scrollbar(main_frame, orient="horizontal", command=self.logs_text.xview)
        h_scrollbar.pack(side='bottom', fill='x')
        self.logs_text.configure(xscrollcommand=h_scrollbar.set)
        
        # Initialize log queue
        self.log_queue = queue.Queue()
        
        # Set up custom log handler
        self.log_handler = CustomLogHandler(self.log_queue)
        import logging
        logging.getLogger().addHandler(self.log_handler)
    
    def _create_settings_tab(self):
        """Create the settings tab."""
        settings = ttk.Frame(self.notebook)
        self.notebook.add(settings, text="Settings")
        
        settings_frame = ttk.Frame(settings, padding=10)
        settings_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        tk.Label(settings_frame, text="Scan Interval (seconds):", font=("Segoe UI", 11), bg="#f4f6fa").pack(anchor='w', padx=10, pady=(10,0))
        self.interval_entry = tk.Entry(settings_frame, font=("Segoe UI", 11))
        self.interval_entry.insert(0, str(config.SCAN_INTERVAL))
        self.interval_entry.pack(anchor='w', padx=10, pady=5)
        
        tk.Label(settings_frame, text="Security Mode:", font=("Segoe UI", 11), bg="#f4f6fa").pack(anchor='w', padx=10, pady=(10,0))
        self.mode_combo = ttk.Combobox(settings_frame, values=["aggressive", "balanced", "passive"], font=("Segoe UI", 11))
        self.mode_combo.set(config.CURRENT_SECURITY_MODE)
        self.mode_combo.pack(anchor='w', padx=10, pady=5)
        
        tk.Button(settings_frame, text="Save Settings", font=("Segoe UI", 11), command=self.parent.events.save_settings).pack(anchor='w', padx=10, pady=15)
    
    def _create_cloud_tab(self):
        """Create the cloud services tab."""
        cloud = ttk.Frame(self.notebook)
        self.notebook.add(cloud, text="Cloud")
        
        # Cloud Services Frame
        services_frame = ttk.LabelFrame(cloud, text="Cloud Services", padding=10)
        services_frame.pack(fill='x', padx=10, pady=5)
        
        # Status label
        status_text = "Cloud services are not configured" if not self.cloud_manager else "Cloud services are available"
        status_label = ttk.Label(services_frame, text=status_text, 
                               foreground="red" if not self.cloud_manager else "green")
        status_label.pack(anchor='w', pady=2)
        
        # Service checkboxes
        ttk.Checkbutton(services_frame, text="Google Drive", variable=self.gdrive_var).pack(anchor='w', pady=2)
        ttk.Checkbutton(services_frame, text="Dropbox", variable=self.dropbox_var).pack(anchor='w', pady=2)
        ttk.Checkbutton(services_frame, text="OneDrive", variable=self.onedrive_var).pack(anchor='w', pady=2)
        ttk.Checkbutton(services_frame, text="GitHub", variable=self.github_var).pack(anchor='w', pady=2)
        
        # Backup Settings Frame
        backup_frame = ttk.LabelFrame(cloud, text="Backup Settings", padding=10)
        backup_frame.pack(fill='x', padx=10, pady=5)
        
        # Backup Interval
        ttk.Label(backup_frame, text="Backup Interval (hours):").pack(anchor='w', pady=2)
        backup_interval_entry = ttk.Entry(backup_frame, textvariable=self.backup_interval)
        backup_interval_entry.pack(anchor='w', pady=2)
        
        # GitHub Repository
        ttk.Label(backup_frame, text="GitHub Repository:").pack(anchor='w', pady=2)
        github_repo_entry = ttk.Entry(backup_frame, textvariable=self.github_repo)
        github_repo_entry.pack(anchor='w', pady=2)
        
        # Buttons
        ttk.Button(cloud, text="Save Cloud Settings", command=self.parent.events.save_cloud_settings).pack(pady=10)
        ttk.Button(cloud, text="Configure Cloud Services", command=self.parent.events.configure_cloud).pack(pady=5)
    
    def _create_monitoring_tab(self):
        """Create the monitoring tab."""
        monitoring = ttk.Frame(self.notebook)
        self.notebook.add(monitoring, text="Monitoring")
        
        monitoring_frame = ttk.Frame(monitoring, padding=10)
        monitoring_frame.pack(fill='both', expand=True)
        
        # Status Overview
        status_frame = ttk.LabelFrame(monitoring_frame, text="System Status", padding=5)
        status_frame.pack(fill='x', padx=5, pady=5)
        
        # System Health
        health_frame = ttk.Frame(status_frame)
        health_frame.pack(fill='x', pady=2)
        ttk.Label(health_frame, text="System Health:").pack(side='left', padx=5)
        self.health_label = ttk.Label(health_frame, text="Good", foreground="green")
        self.health_label.pack(side='left', padx=5)
        
        # Active Monitors
        monitors_frame = ttk.Frame(status_frame)
        monitors_frame.pack(fill='x', pady=2)
        ttk.Label(monitors_frame, text="Active Monitors:").pack(side='left', padx=5)
        self.monitors_label = ttk.Label(monitors_frame, text="0")
        self.monitors_label.pack(side='left', padx=5)
        
        # Last Scan
        scan_frame = ttk.Frame(status_frame)
        scan_frame.pack(fill='x', pady=2)
        ttk.Label(scan_frame, text="Last Scan:").pack(side='left', padx=5)
        self.last_scan_label = ttk.Label(scan_frame, text="Never")
        self.last_scan_label.pack(side='left', padx=5)
        
        # Performance Metrics
        metrics_frame = ttk.LabelFrame(monitoring_frame, text="Performance Metrics", padding=5)
        metrics_frame.pack(fill='x', padx=5, pady=5)
        
        # CPU Usage
        cpu_frame = ttk.Frame(metrics_frame)
        cpu_frame.pack(fill='x', pady=2)
        ttk.Label(cpu_frame, text="CPU Usage:").pack(side='left', padx=5)
        self.cpu_label = ttk.Label(cpu_frame, text="0%")
        self.cpu_label.pack(side='left', padx=5)
        
        # Memory Usage
        memory_frame = ttk.Frame(metrics_frame)
        memory_frame.pack(fill='x', pady=2)
        ttk.Label(memory_frame, text="Memory Usage:").pack(side='left', padx=5)
        self.memory_label = ttk.Label(memory_frame, text="0 MB")
        self.memory_label.pack(side='left', padx=5)
        
        # Activity Log
        log_frame = ttk.LabelFrame(monitoring_frame, text="Activity Log", padding=5)
        log_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Log controls
        controls_frame = ttk.Frame(log_frame)
        controls_frame.pack(fill='x', pady=2)
        
        # Log level filter
        ttk.Label(controls_frame, text="Level:").pack(side='left', padx=5)
        self.log_level = ttk.Combobox(controls_frame, values=["ALL", "INFO", "WARNING", "ERROR", "CRITICAL"],
                                    state="readonly", width=10)
        self.log_level.set("ALL")
        self.log_level.pack(side='left', padx=5)
        self.log_level.bind('<<ComboboxSelected>>', self.parent.events.update_activity_log)
        
        # Search filter
        ttk.Label(controls_frame, text="Search:").pack(side='left', padx=5)
        self.log_search = ttk.Entry(controls_frame, width=30)
        self.log_search.pack(side='left', padx=5)
        self.log_search.bind('<KeyRelease>', self.parent.events.update_activity_log)
        
        # Clear button
        ttk.Button(controls_frame, text="Clear", command=self.parent.events.clear_activity_log).pack(side='right', padx=5)
        
        # Log display
        self.activity_log = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.activity_log.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Configure tags for different log levels
        self.activity_log.tag_configure("INFO", foreground="green")
        self.activity_log.tag_configure("WARNING", foreground="orange")
        self.activity_log.tag_configure("ERROR", foreground="red")
        self.activity_log.tag_configure("CRITICAL", foreground="red", font=("TkDefaultFont", 10, "bold"))
        
        # Activity Graphs
        graphs_frame = ttk.LabelFrame(monitoring_frame, text="Activity Graphs", padding=5)
        graphs_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Create figure for graphs (if matplotlib available)
        if MATPLOTLIB_AVAILABLE:
            self.fig = plt.Figure(figsize=(8, 6))
            self.canvas = FigureCanvasTkAgg(self.fig, master=graphs_frame)
            self.canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            # Placeholder if matplotlib not available
            placeholder = tk.Label(graphs_frame, text="Graphs require matplotlib. Install with: pip install matplotlib", 
                                 fg="gray", wraplength=400)
            placeholder.pack(fill='both', expand=True, pady=20)
            self.fig = None
            self.canvas = None
        
        # Graph controls
        graph_controls = ttk.Frame(graphs_frame)
        graph_controls.pack(fill='x', pady=2)
        
        # Graph type selector
        ttk.Label(graph_controls, text="Graph Type:").pack(side='left', padx=5)
        self.graph_type = ttk.Combobox(graph_controls, 
                                     values=["File Operations", "Security Events", "Performance", "Access Patterns"],
                                     state="readonly", width=20)
        self.graph_type.set("File Operations")
        self.graph_type.pack(side='left', padx=5)
        self.graph_type.bind('<<ComboboxSelected>>', self.parent.events.update_graphs)
        
        # Time range selector
        ttk.Label(graph_controls, text="Time Range:").pack(side='left', padx=5)
        self.time_range = ttk.Combobox(graph_controls,
                                     values=["Last Hour", "Last 24 Hours", "Last Week", "Last Month"],
                                     state="readonly", width=15)
        self.time_range.set("Last 24 Hours")
        self.time_range.pack(side='left', padx=5)
        self.time_range.bind('<<ComboboxSelected>>', self.parent.events.update_graphs)
    
    def _create_lie_detection_tab(self):
        """Create the Zaelith lie detection tab."""
        lie_detection = ttk.Frame(self.notebook)
        self.notebook.add(lie_detection, text="Lie Detection")
        
        main_frame = ttk.Frame(lie_detection, padding=10)
        main_frame.pack(fill='both', expand=True)
        
        # Service Status Frame
        status_frame = ttk.LabelFrame(main_frame, text="Zaelith Service Status", padding=10)
        status_frame.pack(fill='x', padx=5, pady=5)
        
        # Status indicator
        status_row = ttk.Frame(status_frame)
        status_row.pack(fill='x', pady=2)
        ttk.Label(status_row, text="Service Status:").pack(side='left', padx=5)
        
        status_text = "Available" if self.zaelith_available else "Unavailable"
        status_color = "green" if self.zaelith_available else "red"
        self.zaelith_status_label = ttk.Label(status_row, text=status_text, foreground=status_color)
        self.zaelith_status_label.pack(side='left', padx=5)
        
        # Test connection button
        ttk.Button(status_frame, text="Test Connection", 
                  command=self.parent.events.test_zaelith_connection).pack(anchor='w', pady=5)
        
        # Input Frame
        input_frame = ttk.LabelFrame(main_frame, text="Analyze Text Interaction", padding=10)
        input_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Prompt input
        ttk.Label(input_frame, text="Original Prompt/Question:", font=("Segoe UI", 10, "bold")).pack(anchor='w', pady=(0,5))
        
        prompt_frame = ttk.Frame(input_frame)
        prompt_frame.pack(fill='x', pady=(0,10))
        
        self.prompt_text = tk.Text(prompt_frame, height=4, wrap=tk.WORD, 
                                  font=("Consolas", 10), bg="#f8f9fa", 
                                  relief="solid", borderwidth=1)
        self.prompt_text.pack(side='left', fill='both', expand=True, padx=(0,5))
        
        prompt_scrollbar = ttk.Scrollbar(prompt_frame, orient="vertical", 
                                       command=self.prompt_text.yview)
        prompt_scrollbar.pack(side='right', fill='y')
        self.prompt_text.configure(yscrollcommand=prompt_scrollbar.set)
        
        # Response input
        ttk.Label(input_frame, text="Response to Analyze:", font=("Segoe UI", 10, "bold")).pack(anchor='w', pady=(0,5))
        
        response_frame = ttk.Frame(input_frame)
        response_frame.pack(fill='both', expand=True, pady=(0,10))
        
        self.response_text = tk.Text(response_frame, height=6, wrap=tk.WORD, 
                                   font=("Consolas", 10), bg="#f8f9fa", 
                                   relief="solid", borderwidth=1)
        self.response_text.pack(side='left', fill='both', expand=True, padx=(0,5))
        
        response_scrollbar = ttk.Scrollbar(response_frame, orient="vertical", 
                                         command=self.response_text.yview)
        response_scrollbar.pack(side='right', fill='y')
        self.response_text.configure(yscrollcommand=response_scrollbar.set)
        
        # Control buttons
        controls_frame = ttk.Frame(input_frame)
        controls_frame.pack(fill='x', pady=5)
        
        self.analyze_btn = ttk.Button(controls_frame, text="Analyze for Deception", 
                                    command=self.parent.events.run_lie_detection, style="Accent.TButton")
        self.analyze_btn.pack(side='left', padx=5)
        
        ttk.Button(controls_frame, text="Clear All", 
                  command=self.parent.events.clear_lie_detection_inputs).pack(side='left', padx=5)
        
        ttk.Button(controls_frame, text="Load Example", 
                  command=self.parent.events.load_example_text).pack(side='left', padx=5)
        
        ttk.Button(controls_frame, text="Save Analysis", 
                  command=self.parent.events.save_analysis_results).pack(side='right', padx=5)
        
        # Results Frame
        results_frame = ttk.LabelFrame(main_frame, text="Analysis Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Results display with notebook for different views
        results_notebook = ttk.Notebook(results_frame)
        results_notebook.pack(fill='both', expand=True)
        
        # Summary tab
        summary_tab = ttk.Frame(results_notebook)
        results_notebook.add(summary_tab, text="Summary")
        
        self.summary_text = tk.Text(summary_tab, height=8, wrap=tk.WORD, 
                                  font=("Segoe UI", 10), bg="#ffffff", 
                                  relief="solid", borderwidth=1, state='disabled')
        self.summary_text.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Configure text tags for colored output
        self.summary_text.tag_configure("risk_high", foreground="red", font=("Segoe UI", 10, "bold"))
        self.summary_text.tag_configure("risk_medium", foreground="orange", font=("Segoe UI", 10, "bold"))
        self.summary_text.tag_configure("risk_low", foreground="green", font=("Segoe UI", 10, "bold"))
        self.summary_text.tag_configure("header", font=("Segoe UI", 11, "bold"))
        self.summary_text.tag_configure("evidence", foreground="#555", font=("Consolas", 9))
        
        # Detailed tab
        detailed_tab = ttk.Frame(results_notebook)
        results_notebook.add(detailed_tab, text="Detailed Report")
        
        detailed_frame = ttk.Frame(detailed_tab)
        detailed_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        self.detailed_text = tk.Text(detailed_frame, wrap=tk.WORD, 
                                   font=("Consolas", 9), bg="#f8f9fa", 
                                   relief="solid", borderwidth=1, state='disabled')
        self.detailed_text.pack(side='left', fill='both', expand=True)
        
        detailed_scrollbar = ttk.Scrollbar(detailed_frame, orient="vertical", 
                                         command=self.detailed_text.yview)
        detailed_scrollbar.pack(side='right', fill='y')
        self.detailed_text.configure(yscrollcommand=detailed_scrollbar.set)
        
        # History tab
        history_tab = ttk.Frame(results_notebook)
        results_notebook.add(history_tab, text="Analysis History")
        
        history_controls = ttk.Frame(history_tab)
        history_controls.pack(fill='x', padx=5, pady=5)
        
        ttk.Button(history_controls, text="Refresh History", 
                  command=self.parent.events.refresh_analysis_history).pack(side='left', padx=5)
        ttk.Button(history_controls, text="Clear History", 
                  command=self.parent.events.clear_analysis_history).pack(side='left', padx=5)
        
        # History listbox
        history_list_frame = ttk.Frame(history_tab)
        history_list_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        self.history_listbox = tk.Listbox(history_list_frame, font=("Consolas", 9))
        self.history_listbox.pack(side='left', fill='both', expand=True)
        self.history_listbox.bind('<Double-Button-1>', self.parent.events.load_from_history)
        
        history_scrollbar = ttk.Scrollbar(history_list_frame, orient="vertical", 
                                        command=self.history_listbox.yview)
        history_scrollbar.pack(side='right', fill='y')
        self.history_listbox.configure(yscrollcommand=history_scrollbar.set)
    
    def create_tooltip(self, widget, text):
        """Create a tooltip for a given widget."""
        def show_tooltip(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            label = tk.Label(tooltip, text=text, justify='left',
                           background="#ffffe0", relief='solid', borderwidth=1,
                           font=("Segoe UI", "8", "normal"))
            label.pack()
            
            def hide_tooltip():
                tooltip.destroy()
            
            widget.tooltip = tooltip
            widget.bind('<Leave>', lambda e: hide_tooltip())
            tooltip.bind('<Leave>', lambda e: hide_tooltip())
        
        widget.bind('<Enter>', show_tooltip)
    
    def update_log_display(self, event=None):
        """Update the log display based on current filters."""
        self.logs_text.delete(1.0, tk.END)
        
        level_filter = self.level_var.get()
        filter_text = self.filter_var.get().lower()
        
        # Process all entries in the queue
        entries = []
        while not self.log_queue.empty():
            try:
                entries.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        
        # Apply filters and sort by timestamp
        filtered_entries = []
        for entry in entries:
            if level_filter != "ALL" and entry['level'] != level_filter:
                continue
            if filter_text and filter_text not in entry['message'].lower():
                continue
            filtered_entries.append(entry)
        
        # Sort by timestamp
        filtered_entries.sort(key=lambda x: x['timestamp'])
        
        # Display filtered entries
        for entry in filtered_entries:
            timestamp = datetime.fromtimestamp(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            
            # Insert timestamp
            self.logs_text.insert(tk.END, f"[{timestamp}] ", "timestamp")
            
            # Insert level with appropriate tag
            self.logs_text.insert(tk.END, f"{entry['level']} ", entry['level'])
            
            # Insert message
            self.logs_text.insert(tk.END, f"{entry['message']}\n")
            
            # If there's a summary, add it with special formatting
            if 'summary' in entry and entry['summary']:
                self.logs_text.insert(tk.END, f"   {entry['summary']}\n", "summary")
        
        # Scroll to bottom
        self.logs_text.see(tk.END)
    
    def clear_log_filters(self):
        """Clear all log filters."""
        self.level_var.set("ALL")
        self.filter_var.set("")
        self.update_log_display()
    
    def load_directory_history(self):
        """Load directory history from config file."""
        try:
            history_file = Path("config/directory_history.json")
            if history_file.exists():
                with open(history_file, 'r') as f:
                    self.directory_history = json.load(f)
            else:
                self.directory_history = []
        except Exception as e:
            print(f"Failed to load directory history: {e}")
            self.directory_history = []
    
    def save_directory_history(self):
        """Save directory history to config file."""
        try:
            history_file = Path("config/directory_history.json")
            history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(history_file, 'w') as f:
                json.dump(self.directory_history, f)
        except Exception as e:
            print(f"Failed to save directory history: {e}")
    
    def _create_zaelith_tab(self):
        """Create the Zaelith analysis tab (Developer only)."""
        zaelith_frame = ttk.Frame(self.notebook)
        self.notebook.add(zaelith_frame, text="Zaelith Analysis")
        
        # Title
        title_frame = tk.Frame(zaelith_frame, bg="#f4f6fa")
        title_frame.pack(fill='x', pady=10, padx=10)
        
        tk.Label(
            title_frame, 
            text="Zaelith Advanced Analysis", 
            font=("Segoe UI", 18, "bold"), 
            bg="#f4f6fa",
            fg="#2c3e50"
        ).pack(side='left')
        
        # Developer badge
        dev_badge = tk.Label(
            title_frame,
            text="🔒 DEVELOPER ONLY",
            font=("Segoe UI", 10, "bold"),
            bg="#e74c3c",
            fg="white",
            padx=10,
            pady=2
        )
        dev_badge.pack(side='right')
        
        # Main content frame
        content_frame = ttk.Frame(zaelith_frame)
        content_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Left panel - Input
        left_panel = ttk.LabelFrame(content_frame, text="Analysis Input", padding="10")
        left_panel.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        # Text input
        tk.Label(left_panel, text="Text to Analyze:", font=("Segoe UI", 12, "bold")).pack(anchor='w', pady=(0, 5))
        
        self.zaelith_text = tk.Text(
            left_panel,
            height=15,
            width=50,
            font=("Consolas", 10),
            wrap=tk.WORD
        )
        self.zaelith_text.pack(fill='both', expand=True, pady=(0, 10))
        
        # Analysis controls
        controls_frame = ttk.Frame(left_panel)
        controls_frame.pack(fill='x', pady=(0, 10))
        
        # Analysis type
        tk.Label(controls_frame, text="Analysis Type:").pack(side='left', padx=(0, 10))
        self.zaelith_type = ttk.Combobox(
            controls_frame,
            values=["comprehensive", "quick", "deep"],
            state="readonly",
            width=15
        )
        self.zaelith_type.set("comprehensive")
        self.zaelith_type.pack(side='left', padx=(0, 20))
        
        # Analyze button
        analyze_btn = ttk.Button(
            controls_frame,
            text="🔍 Analyze",
            command=self.parent.events.run_zaelith_analysis,
            style="Accent.TButton"
        )
        analyze_btn.pack(side='left', padx=(0, 10))
        
        # Clear button
        clear_btn = ttk.Button(
            controls_frame,
            text="🗑️ Clear",
            command=self._clear_zaelith_input
        )
        clear_btn.pack(side='left')
        
        # Right panel - Results
        right_panel = ttk.LabelFrame(content_frame, text="Analysis Results", padding="10")
        right_panel.pack(side='right', fill='both', expand=True, padx=(5, 0))
        
        # Results display
        self.zaelith_results = tk.Text(
            right_panel,
            height=15,
            width=50,
            font=("Consolas", 10),
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.zaelith_results.pack(fill='both', expand=True, pady=(0, 10))
        
        # Results controls
        results_controls = ttk.Frame(right_panel)
        results_controls.pack(fill='x')
        
        # Export button
        export_btn = ttk.Button(
            results_controls,
            text="💾 Export Results",
            command=self._export_zaelith_results
        )
        export_btn.pack(side='left', padx=(0, 10))
        
        # Clear results button
        clear_results_btn = ttk.Button(
            results_controls,
            text="🗑️ Clear Results",
            command=self._clear_zaelith_results
        )
        clear_results_btn.pack(side='left')
        
        # Status bar for Zaelith
        self.zaelith_status = tk.Label(
            zaelith_frame,
            text="Ready for analysis",
            font=("Segoe UI", 10),
            bg="#ecf0f1",
            fg="#2c3e50",
            relief=tk.SUNKEN,
            anchor='w'
        )
        self.zaelith_status.pack(fill='x', side='bottom')
    
    def _clear_zaelith_input(self):
        """Clear Zaelith input text."""
        self.zaelith_text.delete(1.0, tk.END)
    
    def _clear_zaelith_results(self):
        """Clear Zaelith results."""
        self.zaelith_results.config(state=tk.NORMAL)
        self.zaelith_results.delete(1.0, tk.END)
        self.zaelith_results.config(state=tk.DISABLED)
    
    def _export_zaelith_results(self):
        """Export Zaelith results to file."""
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            
            if filename:
                with open(filename, 'w') as f:
                    f.write(self.zaelith_results.get(1.0, tk.END))
                messagebox.showinfo("Success", f"Results exported to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export results: {e}")
