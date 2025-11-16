#!/usr/bin/env python3
"""
Extract HTML/CSS/JS from simple_webview_auth.py to frontend files.
"""

import re
from pathlib import Path

def extract_content():
    """Extract HTML content from simple_webview_auth.py"""
    source_file = Path(__file__).parent.parent / "ui" / "simple_webview_auth.py"
    frontend_dir = Path(__file__).parent.parent / "frontend"
    
    print(f"Reading {source_file}...")
    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract login HTML (everything between return """ and """)
    login_pattern = r'def _create_login_html\(self\) -> str:.*?return """(.*?)"""'
    login_match = re.search(login_pattern, content, re.DOTALL)
    
    # Extract signup HTML
    signup_pattern = r'def _create_signup_html\(self\) -> str:.*?return """(.*?)"""'
    signup_match = re.search(signup_pattern, content, re.DOTALL)
    
    if not login_match:
        print("❌ Failed to extract login HTML")
        return False
    
    login_html = login_match.group(1).strip()
    
    if not signup_match:
        print("❌ Failed to extract signup HTML")
        return False
    
    signup_html = signup_match.group(1).strip()
    
    # Write login.html
    login_file = frontend_dir / "login.html"
    with open(login_file, 'w', encoding='utf-8') as f:
        f.write(login_html)
    print(f"✅ Created {login_file}")
    
    # Write signup.html
    signup_file = frontend_dir / "signup.html"
    with open(signup_file, 'w', encoding='utf-8') as f:
        f.write(signup_html)
    print(f"✅ Created {signup_file}")
    
    return True

if __name__ == "__main__":
    if extract_content():
        print("\n✅ Frontend extraction complete!")
        print("\nNext steps:")
        print("1. Extract CSS from HTML files to frontend/css/auth.css")
        print("2. Extract JS from HTML files to frontend/js/auth.js")
        print("3. Update HTML files to reference external CSS/JS")
    else:
        print("\n❌ Frontend extraction failed")

