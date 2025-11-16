#!/usr/bin/env python

import os
import re
import subprocess
from typing import List
from datetime import datetime
import logging

def get_unique_ips(file_path: str) -> List[str]:
    """Extract unique IP addresses from netstat output file."""
    ips = set()
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            print(f"File size: {len(content)} bytes")
            
            # Match IP:port pattern
            matches = re.finditer(r'\d+\.\d+\.\d+\.\d+:\d+', content)
            for match in matches:
                # Extract IP and remove port
                ip = match.group(0).split(':')[0]
                ips.add(ip)
                print(f"Found IP: {ip}")
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return []
    except PermissionError:
        print(f"Error: Permission denied when reading {file_path}")
        return []
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return []
    
    return sorted(list(ips))

def perform_nslookup(ip: str) -> None:
    """Perform nslookup for a given IP address."""
    try:
        print(f"\nPerforming nslookup for {ip}...")
        result = subprocess.run(['nslookup', ip], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        if "Non-existent domain" in result.stdout:
            print(f"nslookup failed for {ip}: No reverse DNS record found.")
        else:
            print("Command output:")
            print(result.stdout)
        if result.stderr:
            print("Command errors:")
            print(result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error performing nslookup for {ip}:")
        print(f"Exit code: {e.returncode}")
        print(f"Error output: {e.stderr}")
    except FileNotFoundError:
        print("Error: nslookup command not found. Please ensure it's installed and in your PATH.")
    except Exception as e:
        print(f"Unexpected error for {ip}: {str(e)}")

def main():
    # File path for netstat output
    netstat_file = r"C:\Users\woods\OneDrive\Documents\Personal\Terminal Logs\Network Security Reports\netstatoutputs\netstat_output.txt"
    
    print(f"Checking file: {netstat_file}")
    if not os.path.exists(netstat_file):
        print("Error: File not found!")
        return
    
    # Get unique IPs
    print("\nExtracting IPs from file...")
    ips = get_unique_ips(netstat_file)
    print(f"\nFound {len(ips)} unique IPs:")
    for ip in ips:
        print(f"- {ip}")
    
    if not ips:
        print("No IPs found in the file. Please check the file content.")
        return
    
    # Perform nslookup for each IP
    print("\nStarting nslookup operations...")
    for ip in ips:
        perform_nslookup(ip)

if __name__ == "__main__":
    main()