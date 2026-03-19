"""
Workspace state snapshots (Section 2.5.3).

Captures the entire directory structure and file contents at a point in time,
allowing the agent to "checkpoint" its work and roll back if a complex 
multi-file refactor goes wrong.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Manages workspace checkpoints by copying files to a hidden metadata area.
    """

    def __init__(self, workspace_dir: str, snapshot_dir: str = ".opendev/snapshots"):
        self.workspace_dir = workspace_dir
        self.snapshot_dir = snapshot_dir
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def take_snapshot(self, label: str) -> str:
        """
        Create a new snapshot of the current workspace.
        Returns the snapshot ID.
        """
        timestamp = int(time.time())
        snapshot_id = f"{timestamp}_{label}"
        dest_path = os.path.join(self.snapshot_dir, snapshot_id)
        
        # We only snapshot tracked files (excluding .git, node_modules, etc.)
        self._copy_workspace(self.workspace_dir, dest_path)
        
        logger.info(f"Created workspace snapshot: {snapshot_id}")
        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """ Revert the workspace to a previous snapshot. """
        src_path = os.path.join(self.snapshot_dir, snapshot_id)
        if not os.path.exists(src_path):
            logger.error(f"Snapshot {snapshot_id} not found.")
            return False

        # Clear current workspace (except .git and .opendev)
        self._clear_workspace(self.workspace_dir)
        
        # Restore from snapshot
        self._copy_workspace(src_path, self.workspace_dir)
        
        logger.info(f"Restored workspace from snapshot: {snapshot_id}")
        return True

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """ List available snapshots. """
        if not os.path.exists(self.snapshot_dir):
            return []
            
        snapshots = []
        for d in os.listdir(self.snapshot_dir):
            if os.path.isdir(os.path.join(self.snapshot_dir, d)):
                parts = d.split("_", 1)
                timestamp = int(parts[0]) if parts[0].isdigit() else 0
                label = parts[1] if len(parts) > 1 else ""
                snapshots.append({
                    "id": d,
                    "timestamp": timestamp,
                    "label": label
                })
        
        # Sort by timestamp (newest first)
        snapshots.sort(key=lambda s: s["timestamp"], reverse=True)
        return snapshots

    def _copy_workspace(self, src: str, dst: str) -> None:
        """ Deep copy of the workspace, skipping ignored patterns. """
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)

        ignored = ["node_modules", ".git", ".opendev", "__pycache__", "venv", ".venv"]
        
        for root, dirs, files in os.walk(src):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
            
            # Determine relative path from src
            rel_path = os.path.relpath(root, src)
            if rel_path == ".":
                target_root = dst
            else:
                target_root = os.path.join(dst, rel_path)
                os.makedirs(target_root, exist_ok=True)

            for f in files:
                if f.startswith("."): continue
                shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))

    def _clear_workspace(self, workspace: str) -> None:
        """ Remove all files from the workspace except metadata. """
        ignored = [".git", ".opendev"]
        for entry in os.listdir(workspace):
            if entry in ignored:
                continue
            path = os.path.join(workspace, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
