#!/usr/bin/env python3
"""
Extract CSS and JS from HTML files to separate files.
"""

import re
from pathlib import Path

def extract_and_separate():
    """Extract CSS and JS from HTML files"""
    frontend_dir = Path(__file__).parent.parent / "frontend"
    login_file = frontend_dir / "login.html"
    signup_file = frontend_dir / "signup.html"
    
    # Read login HTML
    with open(login_file, 'r', encoding='utf-8') as f:
        login_html = f.read()
    
    # Extract CSS (everything between <style> and </style>)
    css_pattern = r'<style>(.*?)</style>'
    css_match = re.search(css_pattern, login_html, re.DOTALL)
    
    if css_match:
        css_content = css_match.group(1).strip()
        css_file = frontend_dir / "css" / "auth.css"
        with open(css_file, 'w', encoding='utf-8') as f:
            f.write(css_content)
        print(f"✅ Created {css_file}")
    
    # Extract JS (everything between <script> and </script>, but not the closing tag content)
    js_pattern = r'<script>(.*?)</script>'
    js_matches = re.findall(js_pattern, login_html, re.DOTALL)
    
    if js_matches:
        # Combine all script blocks
        js_content = '\n\n'.join([js.strip() for js in js_matches if js.strip()])
        js_file = frontend_dir / "js" / "auth.js"
        with open(js_file, 'w', encoding='utf-8') as f:
            f.write(js_content)
        print(f"✅ Created {js_file}")
    
    # Update login.html to reference external files
    login_updated = login_html
    # Replace <style>...</style> with <link>
    login_updated = re.sub(
        r'<style>.*?</style>',
        '<link rel="stylesheet" href="css/auth.css">',
        login_updated,
        flags=re.DOTALL
    )
    # Replace <script>...</script> with <script src="...">
    # Keep the last script tag for inline initialization if needed
    script_tags = re.findall(r'<script>(.*?)</script>', login_updated, re.DOTALL)
    if script_tags:
        # Remove all script tags
        login_updated = re.sub(r'<script>.*?</script>', '', login_updated, flags=re.DOTALL)
        # Add external script reference before </body>
        login_updated = login_updated.replace('</body>', '    <script src="js/auth.js"></script>\n</body>')
    
    with open(login_file, 'w', encoding='utf-8') as f:
        f.write(login_updated)
    print(f"✅ Updated {login_file}")
    
    # Do the same for signup.html
    with open(signup_file, 'r', encoding='utf-8') as f:
        signup_html = f.read()
    
    signup_updated = signup_html
    signup_updated = re.sub(
        r'<style>.*?</style>',
        '<link rel="stylesheet" href="css/auth.css">',
        signup_updated,
        flags=re.DOTALL
    )
    signup_updated = re.sub(r'<script>.*?</script>', '', signup_updated, flags=re.DOTALL)
    signup_updated = signup_updated.replace('</body>', '    <script src="js/auth.js"></script>\n</body>')
    
    with open(signup_file, 'w', encoding='utf-8') as f:
        f.write(signup_updated)
    print(f"✅ Updated {signup_file}")
    
    print("\n✅ CSS/JS separation complete!")

if __name__ == "__main__":
    extract_and_separate()

