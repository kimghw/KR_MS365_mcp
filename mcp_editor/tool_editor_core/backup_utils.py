"""
Backup Utilities Module

백업 관리 함수들:
- 파일 백업 생성
- 오래된 백업 정리
"""

import os
import shutil


def backup_file(file_path: str, backup_dir: str, timestamp: str) -> str | None:
    """Create backup of a file with shared timestamp"""
    if not os.path.exists(file_path):
        return None

    os.makedirs(backup_dir, exist_ok=True)
    filename = os.path.basename(file_path)
    backup_path = os.path.join(backup_dir, f"{filename}_{timestamp}.bak")

    shutil.copy2(file_path, backup_path)
    return backup_path


def cleanup_old_backups(backup_dir: str, keep_count: int = 10):
    """Remove old backups keeping only the most recent ones (by timestamp group)"""
    if not os.path.exists(backup_dir):
        return

    # Group backups by timestamp
    backup_groups = {}
    for filename in os.listdir(backup_dir):
        if not filename.endswith(".bak"):
            continue
        # Extract timestamp from filename (format: filename_YYYYMMDD_HHMMSS.bak)
        parts = filename.rsplit("_", 2)
        if len(parts) >= 3:
            timestamp = f"{parts[-2]}_{parts[-1].replace('.bak', '')}"
            if timestamp not in backup_groups:
                backup_groups[timestamp] = []
            backup_groups[timestamp].append(filename)

    # Sort timestamps and remove old groups
    sorted_timestamps = sorted(backup_groups.keys(), reverse=True)
    for old_timestamp in sorted_timestamps[keep_count:]:
        for filename in backup_groups[old_timestamp]:
            try:
                os.remove(os.path.join(backup_dir, filename))
            except Exception as e:
                print(f"Warning: Could not remove old backup {filename}: {e}")
