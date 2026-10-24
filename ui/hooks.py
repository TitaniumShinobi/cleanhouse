"""
UI Hooks Module

Handles all actions that trigger CleanHouse logic and business operations.
This module serves as the bridge between the UI and the core CleanHouse functionality.
"""

import tkinter as tk
from tkinter import messagebox
import threading
import time
import os
import queue
from pathlib import Path
from datetime import datetime

from corefiles import config
from corefiles.passion import ignite_passion, verify_integrity
from corefiles.integrity import IntegrityMonitor, generate_baseline


class UIHooks:
    """
    Handles all business logic hooks and CleanHouse core functionality integration.
    """
    
    def __init__(self, parent):
        self.parent = parent
        self.layout = parent.layout
        # events will be set later to avoid circular dependency
        self.events = None
        # User context (set after authentication)
        self.current_user = None
        self.user_manager = None
    
    def ignite_passion(self, target_dir=None, threshold=3, dry_run=True):
        """
        Main entry point for CleanHouse functionality.
        Maintains compatibility with brain.py integration.
        """
        try:
            if target_dir is None:
                target_dir = Path(self.layout.target_dir.get())
            
            # Run the core CleanHouse functionality
            results = ignite_passion(target_dir=target_dir, threshold=threshold, dry_run=dry_run)
            
            # Update UI with results
            self.update_scan_results(results)
            
            return results
        except Exception as e:
            print(f"Error in ignite_passion: {e}")
            self.update_status("Error", "#e53935")
            return None
    
    def update_status(self, status, color):
        """Update the status display."""
        self.layout.status_var.set(status)
        self.layout.status_label.config(fg=color)
    
    def run_scan(self):
        """Run a scan with timeout and cancellation support."""
        self.update_status("Scanning...", "#ffa000")
        self.layout.scan_progress.set(0)
        self.layout.files_scanned.set(0)
        self.layout.issues_found.set(0)
        self.layout.results_list.delete(0, tk.END)
        target = Path(self.layout.target_dir.get())

        # Check for baseline before scanning
        if not config.INTEGRITY_BASELINE_FILE.exists():
            self.update_status("No Baseline", "#e53935")
            if messagebox.askyesno("Baseline Missing", "No baseline found. Would you like to create one now?"):
                self.init_baseline()
            else:
                self.layout.results_list.insert(tk.END, "No baseline found. Please initialize a baseline before scanning.")
            return

        try:
            # Create a queue for scan results
            result_queue = queue.Queue()
            
            # Start scan in a separate thread
            scan_thread = threading.Thread(
                target=self.run_scan_thread,
                args=(target, result_queue),
                daemon=True
            )
            scan_thread.start()
            
            # Wait for results with timeout
            timeout = 300  # 5 minutes timeout
            start_time = time.time()
            
            while scan_thread.is_alive():
                if time.time() - start_time > timeout:
                    raise TimeoutError("Scan operation timed out")
                
                # Check for cancellation
                if not self.layout.scan_running:
                    self.layout.results_list.insert(tk.END, "Scan cancelled by user")
                    return
                
                # Update progress
                try:
                    result = result_queue.get_nowait()
                    if isinstance(result, Exception):
                        raise result
                    self.update_scan_results(result)
                except queue.Empty:
                    time.sleep(0.1)
                    continue
            
            # Get final results
            while not result_queue.empty():
                result = result_queue.get()
                if isinstance(result, Exception):
                    raise result
                self.update_scan_results(result)
                
        except TimeoutError as e:
            self.update_status("Scan Timeout", "#e53935")
            messagebox.showerror("Scan Error", str(e))
        except Exception as e:
            self.update_status("Scan Error", "#e53935")
            messagebox.showerror("Scan Error", str(e))
        finally:
            self.layout.scan_running = False
            self.layout.scan_btn.config(text="Start Scan", bg="#1976d2")
            self.layout.last_scan.set(time.strftime("%Y-%m-%d %H:%M:%S"))
    
    def run_scan_thread(self, target, result_queue):
        """Run the actual scan in a separate thread."""
        try:
            changed = verify_integrity(target)
            result_queue.put(changed)
            
            results = ignite_passion(target_dir=target, threshold=3, dry_run=True)
            result_queue.put(results)
            
            self.load_logs()
            
            if changed:
                self.update_status("Issues Detected", "#e53935")
            else:
                self.update_status("No Changes Observed", "#4caf50")
                
        except Exception as e:
            result_queue.put(e)
    
    def update_scan_results(self, results):
        """Update the scan results display."""
        if not results or (isinstance(results, list) and not any(results)):
            self.layout.results_list.insert(tk.END, "No integrity or policy signals observed.")
        else:
            for line in results:
                self.layout.results_list.insert(tk.END, line)
                self.layout.files_scanned.set(self.layout.files_scanned.get() + 1)
                if "issue" in line.lower() or "error" in line.lower():
                    self.layout.issues_found.set(self.layout.issues_found.get() + 1)
    
    def run_monitoring(self):
        """Run continuous monitoring."""
        while self.layout.monitoring:
            target = Path(self.layout.target_dir.get())
            changed = verify_integrity(target)
            self.layout.files_scanned.set(len(changed))
            self.layout.issues_found.set(len(changed))
            self.layout.results_list.delete(0, tk.END)
            for issue in changed:
                self.layout.results_list.insert(tk.END, issue)
            if changed:
                self.update_status("Issues Detected", "#e53935")
            else:
                self.update_status("No Changes Observed", "#4caf50")
            time.sleep(int(self.layout.interval_entry.get()))
    
    def load_logs(self):
        """Load logs from file."""
        self.layout.logs_text.delete(1.0, tk.END)
        log_path = str(config.SECURITY_LOG_FILE)
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                self.layout.logs_text.insert(tk.END, f.read())
        else:
            self.layout.logs_text.insert(tk.END, "No logs found.")
    
    def init_baseline(self):
        """Initialize baseline for the selected directory."""
        target = Path(self.layout.target_dir.get())
        
        # Validate target directory
        if not target or not target.exists():
            self.update_status("No Directory Selected", "#e53935")
            messagebox.showerror("Error", "Please select a valid directory first.")
            return
            
        if not target.is_dir():
            self.update_status("Invalid Directory", "#e53935")
            messagebox.showerror("Error", "Selected path is not a directory.")
            return
            
        # Start baseline generation in a separate thread
        try:
            self.update_status("Initializing Baseline...", "#ffa000")
            threading.Thread(target=self.run_baseline, args=(target,), daemon=True).start()
        except Exception as e:
            self.update_status("Baseline Error", "#e53935")
            messagebox.showerror("Baseline Error", str(e))
    
    def run_baseline(self, target):
        """Run baseline generation in a separate thread."""
        try:
            generate_baseline(target)
            self.update_status("Baseline Created", "#4caf50")
            messagebox.showinfo("Baseline", f"Baseline created for {target}")
        except Exception as e:
            self.update_status("Baseline Error", "#e53935")
            messagebox.showerror("Baseline Error", str(e))
    
    def get_integrity_monitor(self):
        """Get or create an integrity monitor instance."""
        if not hasattr(verify_integrity, 'monitor') or verify_integrity.monitor is None:
            verify_integrity.monitor = IntegrityMonitor(config.BASE_DIR)
        return verify_integrity.monitor
    
    def update_directory_stats(self):
        """Update directory statistics display."""
        try:
            if not config.BASE_DIR or not config.BASE_DIR.exists():
                self.layout.dir_size.set("0 MB")
                self.layout.file_count.set(0)
                self.layout.dir_status.set("Not Monitored")
                return
            
            # Calculate directory size and file count
            total_size = 0
            file_count = 0
            
            for path in config.BASE_DIR.rglob("*"):
                if path.is_file():
                    total_size += path.stat().st_size
                    file_count += 1
            
            # Format size
            size_mb = total_size / (1024 * 1024)
            self.layout.dir_size.set(f"{size_mb:.1f} MB")
            self.layout.file_count.set(file_count)
            
            # Update status
            if hasattr(verify_integrity, 'monitor') and verify_integrity.monitor.running:
                self.layout.dir_status.set("Monitoring")
            else:
                self.layout.dir_status.set("Not Monitored")
                
        except Exception as e:
            print(f"Error updating directory stats: {e}")
            self.layout.dir_status.set("Error")
    
    def upload_baseline_thread(self, upload_queue):
        """Run the baseline upload in a separate thread."""
        try:
            self.layout.cloud_manager.upload_baseline(config.INTEGRITY_BASELINE_FILE)
            upload_queue.put("complete")
        except Exception as e:
            upload_queue.put(e)
    
    def start_performance_monitoring(self):
        """Start monitoring system performance."""
        def update_performance():
            try:
                import psutil
                # CPU usage
                cpu_percent = psutil.cpu_percent()
                self.layout.cpu_label.config(text=f"{cpu_percent}%")
                
                # Memory usage
                memory = psutil.Process().memory_info()
                memory_mb = memory.rss / (1024 * 1024)
                self.layout.memory_label.config(text=f"{memory_mb:.1f} MB")
                
                # Update system health
                if cpu_percent > 90 or memory_mb > 1000:
                    self.layout.health_label.config(text="Warning", foreground="orange")
                elif cpu_percent > 95 or memory_mb > 1500:
                    self.layout.health_label.config(text="Critical", foreground="red")
                else:
                    self.layout.health_label.config(text="Good", foreground="green")
                
            except Exception as e:
                print(f"Error updating performance metrics: {e}")
            
            # Schedule next update
            self.parent.after(5000, update_performance)
        
        # Start the first update
        update_performance()
    
    def refresh_zaelith_status(self):
        """Refresh the Zaelith service status display."""
        try:
            if self.layout.zaelith_service:
                service_info = self.layout.zaelith_service.get_service_info()
                status_text = "Available" if service_info["zaelith_available"] else "Detector Unavailable"
                status_color = "green" if service_info["zaelith_available"] else "red"
                
                if hasattr(self.layout, 'zaelith_status_label'):
                    self.layout.zaelith_status_label.config(text=status_text, foreground=status_color)
            else:
                if hasattr(self.layout, 'zaelith_status_label'):
                    self.layout.zaelith_status_label.config(text="Service Unavailable", foreground="red")
                    
        except Exception as e:
            print(f"Error refreshing Zaelith status: {e}")
    
    def display_analysis_results(self, analysis_result, prompt, response):
        """Display analysis results in the results tabs."""
        try:
            # Clear previous results
            self.layout.summary_text.config(state='normal')
            self.layout.summary_text.delete("1.0", tk.END)
            
            self.layout.detailed_text.config(state='normal')
            self.layout.detailed_text.delete("1.0", tk.END)
            
            if not analysis_result["success"]:
                error_msg = analysis_result.get("error", "Unknown error")
                self.layout.summary_text.insert(tk.END, f"Analysis failed: {error_msg}", "risk_high")
                self.layout.detailed_text.insert(tk.END, f"Error: {error_msg}")
            else:
                # Display summary
                self.display_summary(analysis_result)
                
                # Display detailed report
                self.display_detailed_report(analysis_result, prompt, response)
                
        except Exception as e:
            print(f"Error displaying results: {e}")
            self.layout.summary_text.insert(tk.END, f"Display error: {str(e)}", "risk_high")
        finally:
            self.layout.summary_text.config(state='disabled')
            self.layout.detailed_text.config(state='disabled')
    
    def display_summary(self, analysis_result):
        """Display summary results."""
        summary = analysis_result.get("summary", {})
        risk_level = analysis_result.get("risk_level", "unknown")
        recommendations = analysis_result.get("recommendations", [])
        
        # Risk level header
        self.layout.summary_text.insert(tk.END, "═══ DECEPTION ANALYSIS SUMMARY ═══\n\n", "header")
        
        risk_tag = f"risk_{risk_level}"
        risk_text = f"Risk Level: {risk_level.upper()}\n"
        self.layout.summary_text.insert(tk.END, risk_text, risk_tag)
        
        # Key metrics
        if summary:
            grade = summary.get("grade", "Unknown")
            triggered = summary.get("triggered_indicators", 0)
            total = summary.get("total_indicators", 0)
            confidence = summary.get("analysis_confidence", "unknown")
            
            self.layout.summary_text.insert(tk.END, f"Grade: {grade}\n")
            self.layout.summary_text.insert(tk.END, f"Indicators Triggered: {triggered}/{total}\n")
            self.layout.summary_text.insert(tk.END, f"Analysis Confidence: {confidence}\n\n")
            
            # Key findings
            if summary.get("key_findings"):
                self.layout.summary_text.insert(tk.END, "Key Findings:\n", "header")
                for finding in summary["key_findings"]:
                    self.layout.summary_text.insert(tk.END, f"• {finding}\n", "evidence")
                self.layout.summary_text.insert(tk.END, "\n")
        
        # Recommendations
        if recommendations:
            self.layout.summary_text.insert(tk.END, "Recommendations:\n", "header")
            for rec in recommendations:
                self.layout.summary_text.insert(tk.END, f"• {rec}\n")
    
    def display_detailed_report(self, analysis_result, prompt, response):
        """Display detailed analysis report."""
        zaelith_report = analysis_result.get("zaelith_report", {})
        
        self.layout.detailed_text.insert(tk.END, "═══ DETAILED ZAELITH ANALYSIS REPORT ═══\n\n")
        self.layout.detailed_text.insert(tk.END, f"Timestamp: {analysis_result.get('timestamp', 'Unknown')}\n")
        self.layout.detailed_text.insert(tk.END, f"Source: {analysis_result.get('source', 'Unknown')}\n\n")
        
        self.layout.detailed_text.insert(tk.END, f"Prompt Length: {len(prompt)} characters\n")
        self.layout.detailed_text.insert(tk.END, f"Response Length: {len(response)} characters\n\n")
        
        if zaelith_report:
            for criterion, details in zaelith_report.items():
                if criterion == "summary_grade":
                    continue
                
                if isinstance(details, dict):
                    triggered = details.get("triggered", False)
                    status = "TRIGGERED" if triggered else "PASSED"
                    status_marker = "❌" if triggered else "✅"
                    
                    self.layout.detailed_text.insert(tk.END, f"{status_marker} [{criterion.upper()}]: {status}\n")
                    
                    evidence = details.get("evidence", [])
                    if evidence and triggered:
                        self.layout.detailed_text.insert(tk.END, f"   Evidence ({len(evidence)} items):\n")
                        for i, ev in enumerate(evidence[:5], 1):  # Limit to first 5 items
                            self.layout.detailed_text.insert(tk.END, f"   {i}. {ev}\n")
                        if len(evidence) > 5:
                            self.layout.detailed_text.insert(tk.END, f"   ... and {len(evidence) - 5} more\n")
                    self.layout.detailed_text.insert(tk.END, "\n")
            
            # Summary grade
            grade = zaelith_report.get("summary_grade", "Unknown")
            self.layout.detailed_text.insert(tk.END, f"Overall Assessment: {grade}\n")
    
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
    
    def get_user_data_path(self, subpath: str = "") -> Path:
        """Get the path to user's data directory."""
        if not self.user_manager or not self.current_user:
            # Fallback to default directory
            return Path("userdata/default") / subpath
        
        return self.user_manager.get_user_data_path(subpath)
    
    def save_user_scan_results(self, results: dict, scan_type: str = "general"):
        """Save scan results to user's data directory."""
        try:
            if not self.user_manager or not self.current_user:
                return False
            
            # Create scan results directory
            scan_dir = self.get_user_data_path("scan_results")
            scan_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{scan_type}_{timestamp}.json"
            filepath = scan_dir / filename
            
            # Save results
            with open(filepath, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            
            logging.info(f"Scan results saved to {filepath}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to save scan results: {e}")
            return False
    
    def load_user_scan_history(self, scan_type: str = "general", limit: int = 50):
        """Load user's scan history."""
        try:
            if not self.user_manager or not self.current_user:
                return []
            
            scan_dir = self.get_user_data_path("scan_results")
            if not scan_dir.exists():
                return []
            
            # Find scan files
            scan_files = list(scan_dir.glob(f"{scan_type}_*.json"))
            scan_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            # Load recent scans
            history = []
            for filepath in scan_files[:limit]:
                try:
                    with open(filepath, 'r') as f:
                        scan_data = json.load(f)
                        scan_data['filepath'] = str(filepath)
                        history.append(scan_data)
                except Exception as e:
                    logging.warning(f"Failed to load scan file {filepath}: {e}")
            
            return history
            
        except Exception as e:
            logging.error(f"Failed to load scan history: {e}")
            return []
    
    def save_user_logs(self, log_data: str, log_type: str = "general"):
        """Save logs to user's data directory."""
        try:
            if not self.user_manager or not self.current_user:
                return False
            
            # Create logs directory
            logs_dir = self.get_user_data_path("logs")
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with date
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{log_type}_{date_str}.log"
            filepath = logs_dir / filename
            
            # Append to log file
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(f"\n[{datetime.now().isoformat()}] {log_data}\n")
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to save user logs: {e}")
            return False
    
    def get_user_preferences(self) -> dict:
        """Get user preferences."""
        if not self.current_user:
            return {}
        
        return self.current_user.get("preferences", {})
    
    def update_user_preferences(self, preferences: dict) -> bool:
        """Update user preferences."""
        if not self.user_manager or not self.current_user:
            return False
        
        return self.user_manager.update_user_preferences(preferences)
    
    def run_zaelith_analysis(self, text: str, analysis_type: str = "comprehensive") -> dict:
        """Run Zaelith analysis with user data isolation."""
        try:
            # Check access permissions
            if not self.user_manager or not self.user_manager.can_access_module("zaelith"):
                raise PermissionError("Zaelith analysis requires developer access")
            
            # Run analysis (this would integrate with actual Zaelith module)
            # For now, we'll use the basic analysis from events.py
            from .events import UIEvents
            events = UIEvents(self.parent)
            result = events._basic_zaelith_analysis(text, analysis_type)
            
            # Save analysis to user data
            self.save_user_scan_results(result, "zaelith_analysis")
            
            # Log the analysis
            self.save_user_logs(f"Zaelith analysis completed: {analysis_type}", "zaelith")
            
            return result
            
        except Exception as e:
            logging.error(f"Zaelith analysis error: {e}")
            raise
