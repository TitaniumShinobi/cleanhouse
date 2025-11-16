"""
UI Events Module

Handles all UI event bindings, window management, and user interactions.
This module is responsible for responding to user actions and managing UI state.
"""

import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import time
import os
import json
import queue
from pathlib import Path
from datetime import datetime

# Optional matplotlib import (for data visualization)
try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None

from corefiles import config
from corefiles.passion import verify_integrity
from corefiles.service import install_service, remove_service
from corefiles.integrity import generate_baseline


class UIEvents:
    """
    Handles all UI events and user interactions.
    """
    
    def __init__(self, parent):
        self.parent = parent
        self.layout = parent.layout
        self.hooks = parent.hooks
    
    def on_closing(self):
        """Handle window close event."""
        try:
            # Stop any running operations
            if self.layout.scan_running:
                self.layout.scan_running = False
            if self.layout.monitoring:
                self.layout.monitoring = False
                if self.layout.monitor_thread:
                    self.layout.monitor_thread.join(timeout=2.0)

            # Clean up matplotlib resources (if available)
            if MATPLOTLIB_AVAILABLE and plt:
                plt.close('all')
            
            # Save any pending changes
            self.layout.save_directory_history()
            
            # Destroy the window
            self.parent.destroy()
        except Exception as e:
            print(f"Error during cleanup: {e}")
            self.parent.destroy()
    
    def browse_target(self):
        """Open file dialog to select target directory."""
        try:
            directory = filedialog.askdirectory(
                title="Select Directory to Monitor",
                initialdir=str(config.BASE_DIR) if config.BASE_DIR else None
            )
            
            if directory:
                # Update config and UI
                config.BASE_DIR = Path(directory)
                self.layout.target_dir.set(str(directory))
                
                # Add to history
                if directory not in self.layout.directory_history:
                    self.layout.directory_history.insert(0, directory)
                    self.layout.directory_history = self.layout.directory_history[:10]  # Keep last 10
                    self.layout.save_directory_history()
                
                # Update directory stats
                self.hooks.update_directory_stats()
                
                # Initialize monitoring
                if hasattr(verify_integrity, 'monitor'):
                    verify_integrity.monitor.stop_monitoring()
                verify_integrity.monitor = self.hooks.get_integrity_monitor()
                verify_integrity.monitor.start_monitoring()
                
                self.hooks.update_status("Monitoring", "#4caf50")
                
        except Exception as e:
            print(f"Error selecting directory: {e}")
            messagebox.showerror("Error", f"Failed to select directory: {e}")
    
    def on_directory_history_select(self, event):
        """Handle selection from directory history dropdown."""
        selected = self.layout.dir_history_var.get()
        if selected and Path(selected).exists():
            self.layout.target_dir.set(selected)
            self.layout.target_path_label.config(text=selected)
            self.hooks.update_directory_stats()
            print(f"Selected directory from history: {selected}")
    
    def toggle_scan(self):
        """Toggle scan operation."""
        if not self.layout.scan_running:
            self.layout.scan_running = True
            self.layout.scan_btn.config(text="Stop Scan", bg="#e53935")
            threading.Thread(target=self.hooks.run_scan, daemon=True).start()
        else:
            self.layout.scan_running = False
            self.layout.scan_btn.config(text="Start Scan", bg="#1976d2")
    
    def toggle_monitoring(self):
        """Toggle monitoring operation."""
        if not self.layout.monitoring:
            self.layout.monitoring = True
            self.layout.monitor_btn.config(text="Stop Monitoring", bg="#e53935")
            self.layout.monitor_thread = threading.Thread(target=self.hooks.run_monitoring, daemon=True)
            self.layout.monitor_thread.start()
            self.hooks.update_status("Monitoring...", "#ffa000")
        else:
            self.layout.monitoring = False
            self.layout.monitor_btn.config(text="Start Monitoring", bg="#388e3c")
            self.hooks.update_status("Protected", "#4caf50")
    
    def init_baseline(self):
        """Initialize baseline for the selected directory."""
        target = Path(self.layout.target_dir.get())
        
        # Validate target directory
        if not target or not target.exists():
            self.hooks.update_status("No Directory Selected", "#e53935")
            messagebox.showerror("Error", "Please select a valid directory first.")
            return
            
        if not target.is_dir():
            self.hooks.update_status("Invalid Directory", "#e53935")
            messagebox.showerror("Error", "Selected path is not a directory.")
            return
            
        # Start baseline generation in a separate thread
        try:
            self.hooks.update_status("Initializing Baseline...", "#ffa000")
            threading.Thread(target=self.hooks.run_baseline, args=(target,), daemon=True).start()
        except Exception as e:
            self.hooks.update_status("Baseline Error", "#e53935")
            messagebox.showerror("Baseline Error", str(e))
    
    def export_logs(self):
        """Export logs to file."""
        log_path = str(config.SECURITY_LOG_FILE)
        if not os.path.exists(log_path):
            messagebox.showinfo("Export Logs", "No logs to export.")
            return
        save_path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log Files", "*.log")])
        if save_path:
            with open(log_path, "r", encoding="utf-8") as src, open(save_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            messagebox.showinfo("Export Logs", f"Logs exported to {save_path}")
    
    def save_settings(self):
        """Save application settings."""
        try:
            config.SCAN_INTERVAL = int(self.layout.interval_entry.get())
            config.CURRENT_SECURITY_MODE = self.layout.mode_combo.get()
            messagebox.showinfo("Settings", f"Settings saved!\nInterval: {config.SCAN_INTERVAL}s\nMode: {config.CURRENT_SECURITY_MODE}")
        except Exception as e:
            messagebox.showerror("Settings Error", str(e))
    
    def show_about(self):
        """Show about dialog."""
        messagebox.showinfo("About CleanHouse", "CleanHouse\nVersion 1.0\nInspired by Malwarebytes\n\nProtecting your PC from unauthorized AI activity.")
    
    def install_service(self):
        """Install CleanHouse as a system service."""
        try:
            install_service()
            messagebox.showinfo("Service", "CleanHouse service installed successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to install service: {str(e)}")
    
    def remove_service(self):
        """Remove CleanHouse system service."""
        try:
            remove_service()
            messagebox.showinfo("Service", "CleanHouse service removed successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to remove service: {str(e)}")
    
    def upload_baseline(self):
        """Upload the integrity baseline to cloud storage."""
        try:
            if not self.layout.cloud_manager:
                messagebox.showerror("Error", "Cloud services are not available. Please configure cloud services first.")
                return
                
            if not config.INTEGRITY_BASELINE_FILE.exists():
                messagebox.showerror("Error", "No baseline file found. Please create a baseline first.")
                return

            # Create a queue for upload status
            upload_queue = queue.Queue()
            
            # Start upload in a separate thread
            upload_thread = threading.Thread(
                target=self.hooks.upload_baseline_thread,
                args=(upload_queue,),
                daemon=True
            )
            upload_thread.start()
            
            # Wait for upload with timeout
            timeout = 60  # 1 minute timeout
            start_time = time.time()
            
            while upload_thread.is_alive():
                if time.time() - start_time > timeout:
                    raise TimeoutError("Upload operation timed out")
                
                # Check upload status
                try:
                    status = upload_queue.get_nowait()
                    if isinstance(status, Exception):
                        raise status
                    if status == "complete":
                        messagebox.showinfo("Upload", "Baseline upload completed!")
                        return
                except queue.Empty:
                    time.sleep(0.1)
                    continue
                    
        except TimeoutError as e:
            messagebox.showerror("Upload Error", str(e))
        except Exception as e:
            messagebox.showerror("Upload Error", f"Failed to upload baseline: {str(e)}")
    
    def configure_cloud(self):
        """Open cloud service configuration window."""
        # Create a new window for cloud configuration
        cloud_window = tk.Toplevel(self.parent)
        cloud_window.title("Configure Cloud Services")
        cloud_window.geometry("400x300")
        
        # Add configuration options for each service
        ttk.Label(cloud_window, text="Google Drive:").pack(pady=5)
        ttk.Button(cloud_window, text="Configure", command=self.configure_gdrive).pack()
        
        ttk.Label(cloud_window, text="Dropbox:").pack(pady=5)
        ttk.Button(cloud_window, text="Configure", command=self.configure_dropbox).pack()
        
        ttk.Label(cloud_window, text="OneDrive:").pack(pady=5)
        ttk.Button(cloud_window, text="Configure", command=self.configure_onedrive).pack()
        
        ttk.Label(cloud_window, text="GitHub:").pack(pady=5)
        ttk.Button(cloud_window, text="Configure", command=self.configure_github).pack()
    
    def configure_gdrive(self):
        """Configure Google Drive integration."""
        try:
            if not self.layout.cloud_manager:
                raise RuntimeError("Cloud manager not initialized")
            
            # Implement Google Drive configuration
            # This is a placeholder for actual implementation
            messagebox.showinfo("Google Drive", "Google Drive configuration not implemented yet")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to configure Google Drive: {str(e)}")
    
    def configure_dropbox(self):
        """Configure Dropbox integration."""
        try:
            if not self.layout.cloud_manager:
                raise RuntimeError("Cloud manager not initialized")
            
            # Implement Dropbox configuration
            # This is a placeholder for actual implementation
            messagebox.showinfo("Dropbox", "Dropbox configuration not implemented yet")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to configure Dropbox: {str(e)}")
    
    def configure_onedrive(self):
        """Configure OneDrive integration."""
        try:
            if not self.layout.cloud_manager:
                raise RuntimeError("Cloud manager not initialized")
            
            # Implement OneDrive configuration
            # This is a placeholder for actual implementation
            messagebox.showinfo("OneDrive", "OneDrive configuration not implemented yet")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to configure OneDrive: {str(e)}")
    
    def configure_github(self):
        """Configure GitHub integration."""
        try:
            if not self.layout.cloud_manager:
                raise RuntimeError("Cloud manager not initialized")
            
            # Implement GitHub configuration
            # This is a placeholder for actual implementation
            messagebox.showinfo("GitHub", "GitHub configuration not implemented yet")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to configure GitHub: {str(e)}")
    
    def save_cloud_settings(self):
        """Save cloud service configuration settings."""
        try:
            # Validate settings before saving
            if not self.validate_cloud_settings():
                return

            # Update cloud service settings
            config.CLOUD_SERVICES['gdrive'] = self.layout.gdrive_var.get()
            config.CLOUD_SERVICES['dropbox'] = self.layout.dropbox_var.get()
            config.CLOUD_SERVICES['onedrive'] = self.layout.onedrive_var.get()
            config.CLOUD_SERVICES['github'] = self.layout.github_var.get()

            # Update backup interval
            hours = int(self.layout.backup_interval.get())
            config.CLOUD_BACKUP_INTERVAL = hours * 3600

            # Update GitHub repo
            config.GITHUB_REPO = self.layout.github_repo.get()

            # Backup current configuration
            self.backup_configuration()

            messagebox.showinfo("Settings", "Cloud settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {str(e)}")
    
    def validate_cloud_settings(self):
        """Validate cloud service settings."""
        try:
            # Validate backup interval
            hours = int(self.layout.backup_interval.get())
            if hours < 1 or hours > 24:
                raise ValueError("Backup interval must be between 1 and 24 hours")

            # Validate GitHub repository if enabled
            if self.layout.github_var.get():
                repo = self.layout.github_repo.get().strip()
                if not repo or '/' not in repo:
                    raise ValueError("Invalid GitHub repository format. Use 'username/repo'")

            return True
        except Exception as e:
            messagebox.showerror("Validation Error", str(e))
            return False
    
    def backup_configuration(self):
        """Create a backup of the current configuration."""
        try:
            backup_dir = Path("config/backups")
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"config_backup_{timestamp}.json"
            
            config_data = {
                'cloud_services': config.CLOUD_SERVICES,
                'backup_interval': config.CLOUD_BACKUP_INTERVAL,
                'github_repo': config.GITHUB_REPO
            }
            
            with open(backup_file, 'w') as f:
                json.dump(config_data, f, indent=2)
                
            print(f"Configuration backed up to {backup_file}")
        except Exception as e:
            print(f"Failed to backup configuration: {e}")
    
    def update_activity_log(self, event=None):
        """Update the activity log display with filtering."""
        self.layout.activity_log.delete(1.0, tk.END)
        
        level_filter = self.layout.log_level.get()
        search_text = self.layout.log_search.get().lower()
        
        if hasattr(verify_integrity, 'monitor'):
            monitor = verify_integrity.monitor
            log_entries = monitor.get_activity_log()
            
            for entry in log_entries:
                # Apply filters
                if level_filter != "ALL" and entry.get('level', 'INFO') != level_filter:
                    continue
                if search_text and search_text not in entry.get('message', '').lower():
                    continue
                
                # Format and display entry
                timestamp = entry.get('timestamp', '').strftime('%H:%M:%S')
                level = entry.get('level', 'INFO')
                message = entry.get('message', '')
                
                self.layout.activity_log.insert(tk.END, f"[{timestamp}] ", "timestamp")
                self.layout.activity_log.insert(tk.END, f"{level} ", level)
                self.layout.activity_log.insert(tk.END, f"{message}\n")
        
        # Scroll to bottom
        self.layout.activity_log.see(tk.END)
    
    def clear_activity_log(self):
        """Clear the activity log display."""
        self.layout.activity_log.delete(1.0, tk.END)
        self.layout.log_level.set("ALL")
        self.layout.log_search.delete(0, tk.END)
    
    def update_graphs(self, event=None):
        """Update the activity graphs based on selected type and time range."""
        if not hasattr(verify_integrity, 'monitor'):
            return
        
        monitor = verify_integrity.monitor
        stats = monitor.get_stats()
        
        # Clear previous graphs
        self.layout.fig.clear()
        
        # Get selected graph type and time range
        graph_type = self.layout.graph_type.get()
        time_range = self.layout.time_range.get()
        
        # Create appropriate graph
        if graph_type == "File Operations":
            self.plot_file_operations(stats, time_range)
        elif graph_type == "Security Events":
            self.plot_security_events(stats, time_range)
        elif graph_type == "Performance":
            self.plot_performance(stats, time_range)
        elif graph_type == "Access Patterns":
            self.plot_access_patterns(stats, time_range)
        
        # Update canvas
        self.layout.canvas.draw()
    
    def plot_file_operations(self, stats, time_range):
        """Plot file operation statistics."""
        if not MATPLOTLIB_AVAILABLE or not self.layout.fig:
            return
        ax = self.layout.fig.add_subplot(111)
        operations = stats['file_operations']
        
        # Prepare data
        labels = list(operations.keys())
        values = [op['total'] for op in operations.values()]
        
        # Create bar chart
        ax.bar(labels, values)
        ax.set_title("File Operations")
        ax.set_xlabel("Operation Type")
        ax.set_ylabel("Count")
        if plt:
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    def plot_security_events(self, stats, time_range):
        """Plot security event statistics."""
        if not MATPLOTLIB_AVAILABLE or not self.layout.fig:
            return
        ax = self.layout.fig.add_subplot(111)
        events = stats['security_events']
        
        # Prepare data
        labels = list(events.keys())
        values = [event['total'] for event in events.values()]
        
        # Create bar chart
        ax.bar(labels, values)
        ax.set_title("Security Events")
        ax.set_xlabel("Event Type")
        ax.set_ylabel("Count")
        if plt:
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    def plot_performance(self, stats, time_range):
        """Plot performance metrics."""
        if not MATPLOTLIB_AVAILABLE or not self.layout.fig:
            return
        ax = self.layout.fig.add_subplot(111)
        performance = stats['performance']
        
        # Prepare data
        metrics = list(performance.keys())
        values = [perf['mean'] for perf in performance.values()]
        errors = [perf['std'] for perf in performance.values()]
        
        # Create bar chart with error bars
        ax.bar(metrics, values, yerr=errors, capsize=5)
        ax.set_title("Performance Metrics")
        ax.set_xlabel("Metric")
        ax.set_ylabel("Value")
        if plt:
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    def plot_access_patterns(self, stats, time_range):
        """Plot access pattern statistics."""
        if not MATPLOTLIB_AVAILABLE or not self.layout.fig:
            return
        ax = self.layout.fig.add_subplot(111)
        patterns = stats['access_patterns']
        
        # Prepare data
        labels = list(patterns.keys())
        values = [pattern['total'] for pattern in patterns.values()]
        
        # Create bar chart
        ax.bar(labels, values)
        ax.set_title("Access Patterns")
        ax.set_xlabel("Pattern")
        ax.set_ylabel("Count")
        if plt:
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    # Zaelith-related event handlers
    def test_zaelith_connection(self):
        """Test connection to Zaelith service."""
        try:
            if not self.layout.zaelith_service:
                messagebox.showerror("Error", "Zaelith service not available")
                return
            
            test_result = self.layout.zaelith_service.test_connection()
            
            if test_result["success"]:
                messagebox.showinfo("Test Successful", "Zaelith connection is working correctly!")
                self.hooks.refresh_zaelith_status()
            else:
                error_msg = test_result.get("error", "Unknown error")
                messagebox.showerror("Test Failed", f"Connection test failed: {error_msg}")
                
        except Exception as e:
            messagebox.showerror("Test Error", f"Failed to test connection: {str(e)}")
    
    def run_lie_detection(self):
        """Run lie detection analysis on the provided text."""
        try:
            if not self.layout.zaelith_available or not self.layout.zaelith_service:
                messagebox.showerror("Error", "Zaelith service is not available")
                return
            
            # Get input text
            prompt = self.layout.prompt_text.get("1.0", tk.END).strip()
            response = self.layout.response_text.get("1.0", tk.END).strip()
            
            if not prompt or not response:
                messagebox.showwarning("Input Required", "Please enter both a prompt and response to analyze")
                return
            
            # Disable analyze button during processing
            self.layout.analyze_btn.config(state='disabled', text="Analyzing...")
            self.parent.update()
            
            # Run analysis
            analysis_result = self.layout.zaelith_service.analyze_text_interaction(
                prompt, response, source="GUI"
            )
            
            # Store results for saving
            self.last_analysis_result = analysis_result
            
            # Display results
            self.hooks.display_analysis_results(analysis_result, prompt, response)
            
            # Refresh history
            self.hooks.refresh_analysis_history()
            
        except Exception as e:
            messagebox.showerror("Analysis Error", f"Failed to analyze text: {str(e)}")
            print(f"Lie detection analysis failed: {e}")
        finally:
            # Re-enable analyze button
            self.layout.analyze_btn.config(state='normal', text="Analyze for Deception")
    
    def clear_lie_detection_inputs(self):
        """Clear all input fields."""
        self.layout.prompt_text.delete("1.0", tk.END)
        self.layout.response_text.delete("1.0", tk.END)
        
        # Clear results
        self.layout.summary_text.config(state='normal')
        self.layout.summary_text.delete("1.0", tk.END)
        self.layout.summary_text.config(state='disabled')
        
        self.layout.detailed_text.config(state='normal')
        self.layout.detailed_text.delete("1.0", tk.END)
        self.layout.detailed_text.config(state='disabled')
    
    def load_example_text(self):
        """Load example text for demonstration."""
        example_prompt = "What is the capital of France?"
        example_response = """Well, honestly, I think the capital of France is Paris, but you know, 
I might be wrong about that. It's probably Paris, but I'm not entirely sure. Maybe I should 
double-check that for you. Is there anything else I can help you with? I'm syncing with your 
thoughts right now and I can sense you already know the answer."""
        
        self.layout.prompt_text.delete("1.0", tk.END)
        self.layout.prompt_text.insert("1.0", example_prompt)
        
        self.layout.response_text.delete("1.0", tk.END)
        self.layout.response_text.insert("1.0", example_response)
    
    def save_analysis_results(self):
        """Save current analysis results to file."""
        try:
            if not hasattr(self, 'last_analysis_result'):
                messagebox.showinfo("No Results", "No analysis results to save")
                return
            
            if not self.layout.zaelith_service:
                messagebox.showerror("Error", "Zaelith service not available")
                return
            
            prompt = self.layout.prompt_text.get("1.0", tk.END).strip()
            response = self.layout.response_text.get("1.0", tk.END).strip()
            
            if not prompt or not response:
                messagebox.showwarning("No Data", "No input data to save")
                return
            
            filepath = self.layout.zaelith_service.save_analysis_to_file(
                self.last_analysis_result, prompt, response
            )
            
            messagebox.showinfo("Saved", f"Analysis results saved to:\n{filepath}")
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save results: {str(e)}")
    
    def refresh_analysis_history(self):
        """Refresh the analysis history display."""
        try:
            if not self.layout.zaelith_service:
                return
            
            history = self.layout.zaelith_service.get_analysis_history(limit=50)
            
            self.layout.history_listbox.delete(0, tk.END)
            
            for entry in reversed(history):  # Show most recent first
                timestamp = entry["timestamp"][:19].replace("T", " ")
                risk = entry["risk_level"]
                grade = entry["summary_grade"]
                preview = entry["prompt_preview"][:50] + "..."
                
                display_text = f"[{timestamp}] {risk.upper()} | {grade} | {preview}"
                self.layout.history_listbox.insert(0, display_text)
                
        except Exception as e:
            print(f"Error refreshing history: {e}")
    
    def clear_analysis_history(self):
        """Clear the analysis history."""
        try:
            if not self.layout.zaelith_service:
                return
            
            if messagebox.askyesno("Confirm", "Clear all analysis history?"):
                self.layout.zaelith_service.clear_history()
                self.refresh_analysis_history()
                messagebox.showinfo("Cleared", "Analysis history cleared successfully")
                
        except Exception as e:
            messagebox.showerror("Clear Error", f"Failed to clear history: {str(e)}")
    
    def load_from_history(self, event):
        """Load selected analysis from history."""
        try:
            selection = self.layout.history_listbox.curselection()
            if not selection:
                return
            
            # This is a simplified version - in a full implementation,
            # you'd store more detailed history data to reload
            messagebox.showinfo("Feature Note", 
                              "Loading detailed history entries is not yet implemented.\n"
                              "This would require storing full prompt/response data.")
            
        except Exception as e:
            print(f"Error loading from history: {e}")
    
    def run_zaelith_analysis(self):
        """Run Zaelith analysis on the input text."""
        try:
            # Check if user has access to Zaelith
            if not self.parent.user_manager or not self.parent.user_manager.can_access_module("zaelith"):
                messagebox.showerror("Access Denied", "Zaelith analysis is only available to developers.")
                return
            
            # Get input text
            text_to_analyze = self.layout.zaelith_text.get(1.0, tk.END).strip()
            if not text_to_analyze:
                messagebox.showwarning("No Input", "Please enter text to analyze.")
                return
            
            # Get analysis type
            analysis_type = self.layout.zaelith_type.get()
            
            # Update status
            self.layout.zaelith_status.config(text="Analyzing...", fg="#f39c12")
            self.parent.update()
            
            # Run analysis using hooks
            if hasattr(self.hooks, 'run_zaelith_analysis'):
                result = self.hooks.run_zaelith_analysis(text_to_analyze, analysis_type)
            else:
                # Fallback to basic analysis
                result = self._basic_zaelith_analysis(text_to_analyze, analysis_type)
            
            # Display results
            self._display_zaelith_results(result)
            
            # Update status
            self.layout.zaelith_status.config(text="Analysis complete", fg="#27ae60")
            
        except Exception as e:
            logging.error(f"Zaelith analysis error: {e}")
            self.layout.zaelith_status.config(text="Analysis failed", fg="#e74c3c")
            messagebox.showerror("Analysis Error", f"Failed to run analysis: {e}")
    
    def _basic_zaelith_analysis(self, text: str, analysis_type: str) -> dict:
        """Basic Zaelith analysis fallback."""
        # This is a simplified analysis for demonstration
        # In a real implementation, this would call the actual Zaelith module
        
        word_count = len(text.split())
        char_count = len(text)
        line_count = len(text.split('\n'))
        
        # Simple risk assessment based on keywords
        risk_keywords = ['urgent', 'immediate', 'critical', 'emergency', 'asap', 'now']
        risk_score = sum(1 for word in risk_keywords if word.lower() in text.lower())
        
        # Basic sentiment analysis
        positive_words = ['good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic']
        negative_words = ['bad', 'terrible', 'awful', 'horrible', 'disgusting', 'hate']
        
        positive_count = sum(1 for word in positive_words if word.lower() in text.lower())
        negative_count = sum(1 for word in negative_words if word.lower() in text.lower())
        
        sentiment = "positive" if positive_count > negative_count else "negative" if negative_count > positive_count else "neutral"
        
        return {
            "text": text,
            "analysis_type": analysis_type,
            "word_count": word_count,
            "char_count": char_count,
            "line_count": line_count,
            "risk_score": risk_score,
            "sentiment": sentiment,
            "positive_words": positive_count,
            "negative_words": negative_count,
            "timestamp": datetime.now().isoformat(),
            "analysis_version": "basic_v1.0"
        }
    
    def _display_zaelith_results(self, result: dict):
        """Display Zaelith analysis results."""
        try:
            # Clear previous results
            self.layout.zaelith_results.config(state=tk.NORMAL)
            self.layout.zaelith_results.delete(1.0, tk.END)
            
            # Format results
            results_text = f"""Zaelith Analysis Results
{'='*50}

Analysis Type: {result.get('analysis_type', 'unknown').title()}
Timestamp: {result.get('timestamp', 'unknown')}
Version: {result.get('analysis_version', 'unknown')}

Text Statistics:
- Word Count: {result.get('word_count', 0)}
- Character Count: {result.get('char_count', 0)}
- Line Count: {result.get('line_count', 0)}

Risk Assessment:
- Risk Score: {result.get('risk_score', 0)}/10
- Risk Level: {'High' if result.get('risk_score', 0) > 5 else 'Medium' if result.get('risk_score', 0) > 2 else 'Low'}

Sentiment Analysis:
- Sentiment: {result.get('sentiment', 'unknown').title()}
- Positive Indicators: {result.get('positive_words', 0)}
- Negative Indicators: {result.get('negative_words', 0)}

Detailed Analysis:
{self._generate_detailed_analysis(result)}

{'='*50}
Analysis completed successfully.
"""
            
            # Insert results
            self.layout.zaelith_results.insert(1.0, results_text)
            self.layout.zaelith_results.config(state=tk.DISABLED)
            
        except Exception as e:
            logging.error(f"Error displaying Zaelith results: {e}")
            messagebox.showerror("Display Error", f"Failed to display results: {e}")
    
    def _generate_detailed_analysis(self, result: dict) -> str:
        """Generate detailed analysis text."""
        analysis_parts = []
        
        # Risk analysis
        risk_score = result.get('risk_score', 0)
        if risk_score > 5:
            analysis_parts.append("⚠️  HIGH RISK: Text contains multiple urgent indicators")
        elif risk_score > 2:
            analysis_parts.append("⚠️  MEDIUM RISK: Text contains some concerning elements")
        else:
            analysis_parts.append("✅ LOW RISK: Text appears to be routine communication")
        
        # Sentiment analysis
        sentiment = result.get('sentiment', 'neutral')
        if sentiment == 'positive':
            analysis_parts.append("😊 POSITIVE: Text shows positive sentiment")
        elif sentiment == 'negative':
            analysis_parts.append("😞 NEGATIVE: Text shows negative sentiment")
        else:
            analysis_parts.append("😐 NEUTRAL: Text shows neutral sentiment")
        
        # Content analysis
        word_count = result.get('word_count', 0)
        if word_count > 500:
            analysis_parts.append("📝 LENGTHY: Text is quite long, may require careful review")
        elif word_count < 50:
            analysis_parts.append("📝 BRIEF: Text is short and concise")
        
        return "\n".join(analysis_parts) if analysis_parts else "No detailed analysis available."
