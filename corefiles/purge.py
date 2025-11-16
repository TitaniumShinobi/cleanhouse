# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - purge.py
#  File restoration and cleanup.
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────────── Imports ──────────────────────────────────╮
from pathlib import Path
import logging
import shutil
import os
import tempfile
from datetime import datetime
from typing import List, Optional
import json

from . import config
from corefiles.cloud import CloudStorageManager
from corefiles.integrity import verify_integrity, generate_baseline
# ───────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────────── Restoration ────────────────────────────────╮
def restore_file(file_path: Path, dry_run: bool = False) -> bool:
    """Restore a file from cloud storage."""
    try:
        # Validate path
        if not file_path.exists():
            logging.warning(f"Target file {file_path} does not exist")
            return False
            
        # Check write permissions
        if not os.access(file_path.parent, os.W_OK):
            logging.error(f"No write permission for directory {file_path.parent}")
            return False
            
        # Create temporary backup of current file
        temp_backup = file_path.with_suffix(file_path.suffix + '.temp')
        try:
            shutil.copy2(file_path, temp_backup)
            
            # Initialize cloud storage manager
            cloud_manager = CloudStorageManager()
            
            # Attempt to restore from cloud storage
            logging.info(f"Attempting to restore {file_path} from cloud storage")
            
            if dry_run:
                logging.info(f"[DRY RUN] Would restore {file_path} from cloud storage")
                return True
            
            # Try each cloud service in order
            restored = False
            for service in ['github', 'gdrive', 'dropbox', 'onedrive']:
                try:
                    # Download file from cloud service
                    cloud_path = config.CLOUD_PATHS[service] / file_path.name
                    temp_file = config.TEMP_DIR / f"{file_path.name}.{service}"
                    
                    # Download logic would go here
                    # For now, we'll just log the attempt
                    logging.info(f"Attempting to restore from {service}: {cloud_path}")
                    
                    if os.path.exists(temp_file):
                        shutil.copy2(temp_file, file_path)
                        restored = True
                        break
                        
                except Exception as e:
                    logging.error(f"Failed to restore from {service}: {e}")
                    continue
            
            if not restored:
                logging.error(f"Failed to restore {file_path} from any cloud service")
                # Restore from temporary backup
                if temp_backup.exists():
                    shutil.copy2(temp_backup, file_path)
                return False
            
            # Clean up temporary files
            if temp_backup.exists():
                temp_backup.unlink()
            if temp_file.exists():
                temp_file.unlink()
                
            logging.info(f"Successfully restored {file_path}")
            return True
                
        except Exception as e:
            logging.error(f"Error during restoration of {file_path}: {e}")
            # Attempt to restore from temporary backup if it exists
            if temp_backup.exists():
                try:
                    shutil.copy2(temp_backup, file_path)
                except Exception as restore_error:
                    logging.error(f"Failed to restore from temporary backup: {restore_error}")
            return False
            
    except Exception as e:
        logging.error(f"Unexpected error in restore_file: {e}")
        return False

def restore_system(dry_run: bool = False) -> List[str]:
    """Restore system files from cloud storage."""
    results = []
    
    try:
        # Verify integrity to get list of changed files
        changes = verify_integrity(config.BASE_DIR)
        if not changes:
            results.append("No changes detected. System is clean.")
            return results
        
        # Filter out non-file changes
        files_to_restore = []
        for change in changes:
            if change.startswith("File modified:") or change.startswith("New file:"):
                file_path = Path(change.split(": ")[1])
                if file_path.exists():
                    files_to_restore.append(file_path)
        
        if not files_to_restore:
            results.append("No files need restoration.")
            return results
        
        # Restore each file
        restored_count = 0
        failed_count = 0
        
        for file_path in files_to_restore:
            if restore_file(file_path, dry_run):
                restored_count += 1
                results.append(f"✅ Restored: {file_path}")
            else:
                failed_count += 1
                results.append(f"❌ Failed to restore: {file_path}")
        
        # Generate new baseline after restoration
        if not dry_run and restored_count > 0:
            generate_baseline(config.BASE_DIR)
            results.append("📝 Generated new integrity baseline")
        
        # Summary
        results.append(f"\n📊 Restoration Summary:")
        results.append(f"   Files restored: {restored_count}")
        results.append(f"   Files failed: {failed_count}")
        
    except Exception as e:
        error_msg = f"Error during system restoration: {str(e)}"
        logging.error(error_msg)
        results.append(f"💥 {error_msg}")
    
    return results
# ───────────────────────────────────────────────────────────────────────────╯