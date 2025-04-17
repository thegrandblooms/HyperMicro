#!/usr/bin/env python3
"""
Grid Scanner Program

This program uses controller.py to perform grid scans
with configurable parameters and data collection callbacks.
Includes robust file monitoring and scan organization.
"""

import time
from collections import defaultdict
import statistics  # For calculating statistics on timing data
import logging
import numpy as np
import os
import shutil
import re
import glob
import uuid
import threading
from datetime import datetime
from typing import Callable, Tuple, List, Dict, Any, Optional
import sys

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("WARNING: PyAutoGUI not installed. Mouse click mode will not work.")
    print("Install with: pip install pyautogui")

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("WARNING: Watchdog not installed. File monitoring will be limited.")
    print("Install with: pip install watchdog")

# Import the controller
from controller import SimpleArduinoController, OperationMode

#=============================================================================
# USER CONFIGURATION - Edit these settings as needed
#=============================================================================

# Connection Settings
COM_PORT = "COM6"  # Change this to your Arduino's COM port

# Motor Movement Settings
MOTOR_SPEED_X = 1000  # X-axis motor speed (steps/sec)
MOTOR_SPEED_Y = 1000  # Y-axis motor speed (steps/sec)
MOTOR_ACCEL_X = 1500  # X-axis acceleration (steps/sec²) 
MOTOR_ACCEL_Y = 1500  # Y-axis acceleration (steps/sec²)
BACKLASH_COMPENSATION_X = 0
BACKLASH_COMPENSATION_Y = 0

# Grid Scan Settings
X_RANGE = (0, 5000)  # X-axis range in motor steps (min, max)
Y_RANGE = (0, 1600)  # Y-axis range in motor steps (min, max)
X_STEPS = 80  # Number of grid points in X direction
Y_STEPS = 80  # Number of grid points in Y direction
SNAKE_PATTERN = True  # Use snake pattern for more efficient scanning

# Timing Settings
STABILIZATION_DELAY = 0.05  # Delay after movement for stabilization (seconds)
MOVEMENT_TIMEOUT = 12.0  # Timeout for movements (seconds)
POSITION_TOLERANCE = 5  # Tolerance for position verification (steps)

# Data Collection Settings
DATA_COLLECTION_DELAY = 0.02  # Data collection time (seconds)
FILE_WAIT_TIMEOUT = 3.0  # Max time to wait for a file to appear (seconds)
FILE_STABILIZATION_DELAY = 0.3  # Wait time after file detection to ensure it's written (seconds)
FILE_EXTENDED_WAIT = 0.5  # Additional wait time if file is empty (seconds)
MAX_CAPTURE_ATTEMPTS = 10  # Maximum attempts to capture at a position

# Mouse Click Mode Settings
MOUSE_CLICK_MODE = True  # Enable/disable mouse click at each data point
MOUSE_CLICK_POSITION = (513, 57)  # X, Y screen coordinates for mouse click
POST_CLICK_DELAY = 0.001  # Delay after mouse click (seconds)
PRE_CLICK_ANIMATION_DURATION = 0.001  # Duration for mouse movement animation (seconds)
PRE_CLICK_DELAY = 0.001  # Delay between arriving at position and clicking (seconds)

# File Management Settings
BASE_CAPTURE_DIR = "scan"  # Directory where spectrometer software saves files
ORGANIZED_BASE_DIR = "organized_scans"  # Base directory for organized scan data
FILE_PATTERN = r"SpectrumFile_(\d+)\.txt"  # Pattern for capture files
FILE_CHECK_INTERVAL = 0.05  # Interval between file checks (seconds)

# Copy Method Settings
USE_BINARY_COPY = True  # Use direct binary copy for file transfer
USE_SHUTIL_COPY = True  # Use shutil.copy2 as fallback
USE_COMMAND_LINE_COPY = True  # Use command line copy as fallback

# Verification Settings
VERIFY_FILE_SIZE = True  # Verify file size after copy
READ_FILE_CONTENT = True  # Try to read file content for verification

# Scan Organization Settings
PROCESSING_MARKER_FILE = "processing_complete.json"  # File to mark processed scans
SCAN_METADATA_FILE = "scan_metadata.txt"  # File to store scan metadata
DEFAULT_SCAN_COUNTDOWN = 5  # Countdown before starting scan (seconds)

# Logging and Optimization Settings
LOG_LEVEL = logging.INFO  # Default log level
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'  # Log format
VERBOSE_OUTPUT = True  # Enable verbose logging
TIMING_VERBOSE = True  # Whether to show detailed timing information during scan
TIMING_PER_POINT = True  # Whether to store timing data for each point
TIMING_SUMMARY_CHART = True  # Whether to show ASCII charts in timing summary

#=============================================================================
# FILE MANAGEMENT SYSTEM
#=============================================================================

class SpectrumFileHandler(FileSystemEventHandler):
    """File system event handler for detecting spectrum file creation"""
    
    def __init__(self, expected_filename_pattern, callback):
        self.expected_filename_pattern = expected_filename_pattern
        self.callback = callback
        self.detected_file = None
        
    def on_created(self, event):
        if not event.is_directory and re.match(self.expected_filename_pattern, os.path.basename(event.src_path)):
            self.detected_file = event.src_path
            self.callback(event.src_path)

class ScanFileManager:
    """Manages file organization and tracking for spectral scans"""
    
    def __init__(self, base_capture_dir=BASE_CAPTURE_DIR, organized_base_dir=ORGANIZED_BASE_DIR):
        """
        Initialize the file manager with source and destination directories
        
        Args:
            base_capture_dir: Directory where spectrometer software saves files
            organized_base_dir: Base directory for organized scan data
        """
        self.base_capture_dir = base_capture_dir
        self.organized_base_dir = organized_base_dir
        self.current_scan_id = None
        self.current_scan_dir = None
        self.last_file_count = 0
        self.file_pattern = re.compile(FILE_PATTERN)
        
        # Create directories if they don't exist
        os.makedirs(self.base_capture_dir, exist_ok=True)
        os.makedirs(self.organized_base_dir, exist_ok=True)
        
    def start_new_scan(self, scan_name=None):
        """Start a new scan with a unique identifier and directory"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_scan_id = f"{timestamp}_{scan_name or str(uuid.uuid4())[:8]}"
        self.current_scan_dir = os.path.join(self.organized_base_dir, self.current_scan_id)
        
        # Create organized directory
        os.makedirs(self.current_scan_dir, exist_ok=True)
        
        print(f"Started new scan: {self.current_scan_id}")
        print(f"Files will be organized in: {self.current_scan_dir}")
        
        # Get current file count for tracking
        self.last_file_count = len(self._get_capture_files())
        
        return self.current_scan_id
    
    def _get_capture_files(self):
        """Get list of capture files in the base directory"""
        if not os.path.exists(self.base_capture_dir):
            return []
        return glob.glob(os.path.join(self.base_capture_dir, "SpectrumFile_*.txt"))
    
    def inspect_scan_directory(scan_dir="scan"):
        """
        Utility function to inspect files in the scan directory
        """
        if not os.path.exists(scan_dir):
            print(f"Scan directory {scan_dir} does not exist")
            return
        
        files = glob.glob(os.path.join(scan_dir, "SpectrumFile_*.txt"))
        if not files:
            print(f"No spectrum files found in {scan_dir}")
            return
        
        print(f"Found {len(files)} spectrum files")
        
        # Sort by modification time (newest first)
        files.sort(key=os.path.getmtime, reverse=True)
        
        # Check the newest 3 files
        for i, file_path in enumerate(files[:3]):
            file_size = os.path.getsize(file_path)
            mod_time = time.ctime(os.path.getmtime(file_path))
            
            print(f"\nFile {i+1}: {os.path.basename(file_path)}")
            print(f"  Path: {file_path}")
            print(f"  Size: {file_size} bytes")
            print(f"  Modified: {mod_time}")
            
            if file_size == 0:
                print("  EMPTY FILE!")
            else:
                # Try to read the file content
                try:
                    with open(file_path, 'r') as f:
                        lines = f.readlines()
                    
                    print(f"  Contains {len(lines)} lines")
                    if lines:
                        # Print first 2 lines and last line
                        print(f"  First line: {lines[0].strip()}")
                        if len(lines) > 1:
                            print(f"  Second line: {lines[1].strip()}")
                        print(f"  Last line: {lines[-1].strip()}")
                except Exception as e:
                    print(f"  Error reading file: {e}")
        
        return files

    def wait_for_new_file(self, timeout=FILE_WAIT_TIMEOUT, check_interval=FILE_CHECK_INTERVAL, file_stabilization_delay=FILE_STABILIZATION_DELAY):
        """
        Wait for a new file to appear in the capture directory and stabilize
        
        Args:
            timeout: Maximum time to wait in seconds
            check_interval: How often to check for new files
            file_stabilization_delay: Delay after file creation to ensure it's fully written
            
        Returns:
            Path to new file or None if timeout
        """
        start_time = time.time()
        initial_files = set(self._get_capture_files())
        
        print(f"Waiting for new file (timeout: {timeout}s)...")
        print(f"Current file count: {len(initial_files)}")
        
        while time.time() - start_time < timeout:
            # Get current files
            current_files = set(self._get_capture_files())
            
            # Find new files
            new_files = current_files - initial_files
            
            if new_files:
                # Found at least one new file
                newest_file = max(new_files, key=os.path.getmtime)
                print(f"New file detected: {os.path.basename(newest_file)}")
                
                # Wait for file to stabilize and have content
                print(f"Waiting {file_stabilization_delay}s for file to stabilize...")
                time.sleep(file_stabilization_delay)
                
                # After waiting, check file size to see if it has content
                if os.path.exists(newest_file):  # Make sure file still exists
                    file_size = os.path.getsize(newest_file)
                    print(f"File size after stabilization: {file_size} bytes")
                    
                    if file_size > 0:
                        # File has content
                        print(f"✅ File has content: {os.path.basename(newest_file)}")
                        self.last_file_count = len(current_files)
                        return newest_file
                    else:
                        # File is still empty, try waiting longer
                        print(f"File is still empty, waiting longer...")
                        
                        # Wait for more time and check again
                        time.sleep(FILE_EXTENDED_WAIT)
                        
                        if os.path.exists(newest_file):
                            file_size = os.path.getsize(newest_file)
                            print(f"File size after extended wait: {file_size} bytes")
                            
                            if file_size > 0:
                                print(f"✅ File now has content: {os.path.basename(newest_file)}")
                                self.last_file_count = len(current_files)
                                return newest_file
                            else:
                                print(f"⚠️ File still empty after extended wait. Adding to known files.")
                                # Continue waiting for another file
                                initial_files.add(newest_file)
                else:
                    print(f"⚠️ File disappeared during stabilization period")
            
            time.sleep(check_interval)
        
        print(f"Timeout waiting for new file after {timeout}s")
        return None

    
    def process_capture_file(self, x_idx, y_idx, file_path=None, max_wait=FILE_WAIT_TIMEOUT, stabilization_delay=FILE_STABILIZATION_DELAY):
        """
        Process a capture file - either the specified file or wait for a new one
        
        Args:
            x_idx: X grid index
            y_idx: Y grid index
            file_path: Specific file to process (None to wait for new file)
            max_wait: Maximum time to wait for new file
            stabilization_delay: Time to wait for file to stabilize
            
        Returns:
            Dictionary with file information or None if failed
        """
        if not self.current_scan_dir:
            raise ValueError("No active scan. Call start_new_scan() first")
        
        # If no file specified, wait for new file
        if file_path is None:
            file_path = self.wait_for_new_file(timeout=max_wait, file_stabilization_delay=stabilization_delay)
            
            if not file_path:
                print(f"❌ No new file detected within {max_wait} seconds")
                return None
        
        # Verify file exists and has content
        if not os.path.exists(file_path):
            print(f"❌ File does not exist: {file_path}")
            return None
        
        src_size = os.path.getsize(file_path)
        if src_size == 0:
            print(f"❌ Source file is empty: {file_path}")
            
            # Try waiting a bit more to see if file gets content
            print(f"Waiting additional {stabilization_delay}s for content...")
            time.sleep(stabilization_delay)
            
            if os.path.exists(file_path):
                src_size = os.path.getsize(file_path)
                if src_size == 0:
                    print(f"❌ Source file is still empty after additional wait")
                    return None
                else:
                    print(f"✅ Source file now has content: {src_size} bytes")
            else:
                print(f"❌ Source file disappeared during wait")
                return None
        
        print(f"Source file: {file_path}")
        print(f"Source file size: {src_size} bytes")
        
        # Create new filename with grid position
        base_name = os.path.basename(file_path)
        file_extension = os.path.splitext(base_name)[1]
        new_filename = f"scan_{self.current_scan_id}_x{x_idx:03d}_y{y_idx:03d}{file_extension}"
        new_path = os.path.join(self.current_scan_dir, new_filename)
        
        # Ensure destination directory exists
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        
        # Windows-friendly copy
        copy_success = False
        
        # Method 1: Binary copy
        if USE_BINARY_COPY and not copy_success:
            try:
                # Read entire file content
                with open(file_path, 'rb') as src_file:
                    content = src_file.read()
                    print(f"Read {len(content)} bytes from source")
                
                # Write to destination
                with open(new_path, 'wb') as dest_file:
                    dest_file.write(content)
                
                # Verify copy
                if VERIFY_FILE_SIZE and os.path.exists(new_path):
                    dest_size = os.path.getsize(new_path)
                    print(f"Destination size: {dest_size} bytes")
                    
                    if dest_size == src_size and dest_size > 0:
                        print(f"✅ Binary copy successful")
                        copy_success = True
                    else:
                        print(f"❌ Binary copy verification failed: Source={src_size}, Dest={dest_size}")
                else:
                    print(f"✅ Binary copy completed")
                    copy_success = True
            except Exception as e:
                print(f"❌ Error during binary copy: {e}")
        
        # Method 2: Using shutil.copy2
        if USE_SHUTIL_COPY and not copy_success:
            try:
                print("Trying shutil.copy2...")
                shutil.copy2(file_path, new_path)
                
                if VERIFY_FILE_SIZE and os.path.exists(new_path):
                    dest_size = os.path.getsize(new_path)
                    print(f"Destination size after shutil.copy2: {dest_size} bytes")
                    
                    if dest_size == src_size and dest_size > 0:
                        print(f"✅ shutil.copy2 successful")
                        copy_success = True
                    else:
                        print(f"❌ shutil.copy2 verification failed: Source={src_size}, Dest={dest_size}")
                else:
                    print(f"✅ shutil.copy2 completed")
                    copy_success = True
            except Exception as e:
                print(f"❌ Error during shutil.copy2: {e}")
        
        # Method 3: Using command line copy
        if USE_COMMAND_LINE_COPY and not copy_success:
            try:
                import subprocess
                print("Trying command line copy...")
                
                if os.name == 'nt':  # Windows
                    result = subprocess.run(f'copy /b /y "{file_path}" "{new_path}"', shell=True, capture_output=True)
                else:  # Unix/Linux/Mac
                    result = subprocess.run(f'cp "{file_path}" "{new_path}"', shell=True, capture_output=True)
                
                if VERIFY_FILE_SIZE and os.path.exists(new_path):
                    dest_size = os.path.getsize(new_path)
                    print(f"Destination size after command line copy: {dest_size} bytes")
                    
                    if dest_size == src_size and dest_size > 0:
                        print(f"✅ Command line copy successful")
                        copy_success = True
                    else:
                        print(f"❌ Command line copy verification failed: Source={src_size}, Dest={dest_size}")
                else:
                    print(f"✅ Command line copy completed")
                    copy_success = True
            except Exception as e:
                print(f"❌ Error during command line copy: {e}")
        
        # Verify content of destination file
        if copy_success and READ_FILE_CONTENT:
            try:
                # Test read the file to verify content
                with open(new_path, 'r', errors='ignore') as f:
                    first_line = f.readline()
                    if first_line:
                        print(f"✅ Verified file content: First line reads: {first_line[:30]}...")
                    else:
                        print(f"⚠️ File opened successfully but no content found")
            except Exception as e:
                print(f"⚠️ File content verification warning: {e}")
        
        # Check if any copy method succeeded
        if copy_success:
            return {
                'original_path': file_path,
                'organized_path': new_path,
                'x_idx': x_idx,
                'y_idx': y_idx,
                'timestamp': time.time(),
                'file_size': os.path.getsize(new_path) if os.path.exists(new_path) else 0
            }
        else:
            print(f"❌ All copy methods failed for {file_path} to {new_path}")
            return None
            
    def setup_file_monitoring(self, x_idx, y_idx, callback=None):
        """
        Set up active file monitoring for a specific grid position
        
        Args:
            x_idx: X grid index
            y_idx: Y grid index
            callback: Optional callback for when a file is detected
            
        Returns:
            Tuple of (observer, handler, event_detected)
        """
        if not WATCHDOG_AVAILABLE:
            print("Warning: Watchdog not available, falling back to polling method")
            return None, None, None
            
        # Set up pattern to match files for this position
        expected_pattern = f"SpectrumFile_.*\.txt"
        event_detected = threading.Event()
        
        def file_detected_callback(filename):
            print(f"File detected: {os.path.basename(filename)}")
            # Process the file
            file_info = self.process_capture_file(x_idx, y_idx, file_path=filename)
            # Signal the event
            event_detected.set()
            # Call the user callback if provided
            if callback and file_info:
                callback(file_info)
        
        # Create handler and observer
        handler = SpectrumFileHandler(expected_pattern, file_detected_callback)
        observer = Observer()
        observer.schedule(handler, self.base_capture_dir, recursive=False)
        observer.start()
        
        return observer, handler, event_detected

# Create global file manager
file_manager = ScanFileManager()

#=============================================================================
# CAPTURE FUNCTIONS
#=============================================================================

def standard_data_collection(x, y, x_idx, y_idx):
    """
    Default data collection function that simply returns position info
    
    Args:
        x, y: Motor position in steps
        x_idx, y_idx: Grid indices
        
    Returns:
        Dictionary with measurement data
    """
    print(f"\nData collection at position ({x}, {y}), grid index ({x_idx}, {y_idx})")
    
    # Simulate data collection
    time.sleep(DATA_COLLECTION_DELAY)
    
    return {
        'value': x_idx * y_idx + x_idx + y_idx,
        'position': (x, y),
        'timestamp': time.time()
    }

def mouse_click_data_collection(x, y, x_idx, y_idx):
    """
    Modified data collection function that only performs the click
    and returns expected file information without waiting for processing
    """
    if not PYAUTOGUI_AVAILABLE or not MOUSE_CLICK_MODE:
        print("Mouse click mode is disabled or PyAutoGUI not available")
        return {
            'position': (x, y),
            'grid_idx': (x_idx, y_idx),
            'timestamp': time.time(),
            'mouse_clicked': False,
            'file_captured': False,
            'pending_processing': True  # Flag to indicate async processing
        }
    
    try:
        # Get file count before click
        initial_files = glob.glob(os.path.join(file_manager.base_capture_dir, "SpectrumFile_*.txt"))
        
        # Try to predict next file name
        expected_file = None
        if initial_files:
            file_numbers = []
            for f in initial_files:
                match = re.search(r'SpectrumFile_(\d+)\.txt', os.path.basename(f))
                if match:
                    file_numbers.append(int(match.group(1)))
            
            if file_numbers:
                next_number = max(file_numbers) + 1
                expected_file = os.path.join(file_manager.base_capture_dir, f"SpectrumFile_{next_number}.txt")
        
        # Perform the click
        click_x, click_y = MOUSE_CLICK_POSITION
        print(f"🖱️ CLICKING at position ({click_x}, {click_y})")
        
        # Simplified click with minimal delays
        pyautogui.moveTo(click_x, click_y, duration=0.1)
        time.sleep(0.05)
        pyautogui.click(click_x, click_y)
        time.sleep(0.05)
        
        # Return click information with expected file
        return {
            'position': (x, y),
            'grid_idx': (x_idx, y_idx),
            'timestamp': time.time(),
            'mouse_clicked': True,
            'file_captured': False,  # Not yet confirmed
            'expected_file': expected_file,
            'pending_processing': True  # Flag to indicate async processing
        }
    
    except Exception as e:
        print(f"❌ ERROR during mouse click: {e}")
        return {
            'position': (x, y),
            'grid_idx': (x_idx, y_idx),
            'timestamp': time.time(),
            'mouse_clicked': False,
            'file_captured': False,
            'error': str(e)
        }
    
#=============================================================================
# SCANNER IMPLEMENTATION
#=============================================================================
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GridScanner")

class GridScanner:
    """
    Grid Scanner that uses Arduino controller to move to specified grid points,
    with configurable parameters and callback for data acquisition.
    """

    # Time Tracking and progress reporting
    def _show_progress(self, current_index):
        """Show detailed progress information with timing"""
        completed = current_index + 1
        total = len(self.grid_points)
        percent = (completed / total * 100) if total > 0 else 0
        
        # Calculate ETA
        elapsed = time.time() - self.stats['start_time']
        if completed > 0 and elapsed > 0:
            points_per_sec = completed / elapsed
            remaining = (total - completed) / points_per_sec if points_per_sec > 0 else 0
            
            # Calculate timing breakdown for progress display
            timing_breakdowns = []
            total_accounted = 0
            
            # Only show significant timing categories
            for category in ['movement_time', 'data_collection_time', 'file_wait_time', 
                            'stabilization_time', 'retry_time']:
                if category in self.stats and self.stats[category] > 0:
                    percent_time = (self.stats[category] / elapsed) * 100
                    if percent_time > 1.0:  # Only show if > 1%
                        timing_breakdowns.append(f"{category.split('_')[0]}: {percent_time:.1f}%")
                        total_accounted += self.stats[category]
            
            # Add overhead
            overhead_percent = ((elapsed - total_accounted) / elapsed) * 100
            if overhead_percent > 1.0:
                timing_breakdowns.append(f"overhead: {overhead_percent:.1f}%")
            
            timing_str = " | ".join(timing_breakdowns)
            
            print(f"\rProgress: {completed}/{total} points " +
                f"({percent:.1f}%) - " +
                f"Captures: {self.stats['successful_captures']}/{completed} - " +
                f"Rate: {points_per_sec:.2f} pts/s - " +
                f"ETA: {int(remaining/60)}m {int(remaining%60)}s | " +
                f"{timing_str}", end="")

    def _show_timing_summary(self):
        """Show detailed timing summary at the end of scan"""
        # Calculate actual total time from components
        component_time = (
            self.stats.get('movement_time', 0) +
            self.stats.get('stabilization_time', 0) +
            self.stats.get('position_verification_time', 0) +
            self.stats.get('data_collection_time', 0) +
            self.stats.get('file_processing_time', 0) +
            self.stats.get('overhead_time', 0)
        )
        
        # Use the larger of calculated time or elapsed time
        total_time = max(
            self.stats.get('total_elapsed_time', 0),
            component_time
        )
        
        # Update total_elapsed_time
        self.stats['total_elapsed_time'] = total_time
        
        print("\n\n===== SCAN TIMING SUMMARY =====")
        print(f"Total scan time: {total_time:.2f}s ({total_time/60:.2f} minutes)")
        print(f"Points captured: {self.stats['successful_captures']}/{self.stats['points_completed']}")
        print(f"Average time per point: {total_time/self.stats['points_completed']:.3f}s")
        print(f"Scan rate: {self.stats['points_per_second']:.2f} points/second")
        
        # Print time breakdown by category
        print("\nTime breakdown:")
        categories = [
            ('movement_time', 'Motor Movement'),
            ('stabilization_time', 'Motor Stabilization'),
            ('position_verification_time', 'Position Verification'),
            ('data_collection_time', 'Data Collection'),
            ('file_processing_time', 'File Processing'),
            ('file_wait_time', 'File Waiting'),
            ('click_time', 'Mouse Clicks'),
            ('retry_time', 'Retries'),
            ('overhead_time', 'Overhead/Other')
        ]
        
        # Find the longest category name for formatting
        max_len = max(len(name) for _, name in categories)
        
        # Print each category
        for key, name in categories:
            if key in self.stats:
                time_value = self.stats[key]
                percent = (time_value / total_time) * 100 if total_time > 0 else 0
                
                # Create a bar chart
                bar_width = 40
                bar_length = int((percent / 100) * bar_width)
                bar = '█' * bar_length + '░' * (bar_width - bar_length)
                
                print(f"{name.ljust(max_len)}: {time_value:.2f}s ({percent:.1f}%) {bar}")
        
        # If we have per-point timing data and statistics module is available
        if TIMING_PER_POINT and self.timing_data:
            print("\nTiming statistics by category:")
            
            for key, name in categories:
                if key in self.timing_data and len(self.timing_data[key]) > 0:
                    times = self.timing_data[key]
                    
                    # Calculate statistics
                    try:
                        min_time = min(times)
                        max_time = max(times)
                        avg_time = sum(times) / len(times)
                        
                        # Calculate median and percentiles if possible
                        if len(times) > 1:
                            median = statistics.median(times)
                            p90 = sorted(times)[int(len(times) * 0.9)]
                            
                            print(f"{name.ljust(max_len)}: " +
                                f"min={min_time:.3f}s, " +
                                f"avg={avg_time:.3f}s, " +
                                f"median={median:.3f}s, " +
                                f"90%={p90:.3f}s, " +
                                f"max={max_time:.3f}s")
                    except Exception as e:
                        print(f"{name.ljust(max_len)}: Error calculating statistics - {e}")
        
        # Suggestions for improvement
        print("\nSuggestions for improvement:")
        
        # Check if data collection is the bottleneck
        if self.stats.get('data_collection_time', 0) > total_time * 0.5:
            print("- Data collection is taking >50% of scan time. Consider optimizing the data collection process.")
        
        # Check for excessive file waiting
        if self.stats.get('file_wait_time', 0) > total_time * 0.3:
            print("- File waiting is taking >30% of scan time. Check if file creation can be accelerated.")
        
        # Check if motor movement is slow
        if self.stats.get('movement_time', 0) > total_time * 0.4:
            print("- Motor movement is taking >40% of scan time. Consider increasing motor speed.")
        
        # Check for too many retries
        if self.stats.get('retry_time', 0) > total_time * 0.2:
            print("- Retries are taking >20% of scan time. Investigate why captures are failing.")
        
        # Check overhead time
        if self.stats.get('overhead_time', 0) > total_time * 0.3:
            print("- Overhead time is high (>30%). Look for unaccounted operations or processes.")
        
        print("================================")

    
    def __init__(self, port, config=None, verbose=False):
        """
        Initialize the Grid Scanner.
        
        Args:
            port: Serial port for Arduino controller
            config: Optional configuration dictionary
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        
        # Default configuration
        self.config = {
            # Motor Movement Parameters
            'motor_speed_x': MOTOR_SPEED_X,
            'motor_speed_y': MOTOR_SPEED_Y,
            'motor_accel_x': MOTOR_ACCEL_X,
            'motor_accel_y': MOTOR_ACCEL_Y,
            'backlash_x': BACKLASH_COMPENSATION_X,  # Default X backlash in steps
            'backlash_y': BACKLASH_COMPENSATION_Y,  # Default Y backlash in steps
            'backlash_compensation': True,  # Enable compensation by default
            
            # Grid Parameters
            'x_range': X_RANGE,
            'y_range': Y_RANGE,
            'x_steps': X_STEPS,
            'y_steps': Y_STEPS,
            'snake_pattern': SNAKE_PATTERN,
            
            # Timing Parameters
            'stabilization_delay': STABILIZATION_DELAY,
            'movement_timeout': MOVEMENT_TIMEOUT,
            'position_tolerance': POSITION_TOLERANCE,
            
            # Data Collection Parameters
            'data_timeout': 3.0,               # Max time to wait for data collection (seconds)
            'max_capture_attempts': MAX_CAPTURE_ATTEMPTS,  # Max attempts for each point
            'skip_failed_captures': False,      # Whether to skip points that fail to capture
        }
        
        # Update with user config if provided
        if config:
            self.config.update(config)
        
        # Initialize controller
        self.controller = SimpleArduinoController(port, verbose=verbose)
        self.connected = False
        
        # Scan state
        self.grid_points = []
        self.current_index = -1
        
        # Data storage
        self.scan_data = {}
        self.failed_points = []
        
        # Statistics
        self.stats = {
            'points_completed': 0,
            'total_points': 0,
            'successful_captures': 0,
            'failed_captures': 0,
            'retried_points': 0,
            'skipped_points': 0,
            'start_time': 0,
            'end_time': 0,
            'total_elapsed_time': 0,
            
            # Detailed timing categories
            'movement_time': 0,  # Time spent moving motors
            'stabilization_time': 0,  # Time waiting for motors to stabilize
            'position_verification_time': 0,  # Time verifying position reached
            'data_collection_time': 0,  # Time in data collection callback
            'file_wait_time': 0,  # Time waiting for files to appear
            'file_stabilization_time': 0,  # Time waiting for files to stabilize
            'file_copy_time': 0,  # Time copying files
            'click_time': 0,  # Time spent doing mouse clicks
            'retry_time': 0,  # Time spent on retries
            'overhead_time': 0,  # Other time not accounted for
        }

        # Per-point timing data (if enabled)
        self.timing_data = defaultdict(list)
        
        # Current point timing data
        self.current_point_timing = {}

        # File processing queue
        self.pending_files = []  # [(file_path, x_idx, y_idx), ...]
        self.last_click_position = None  # Store last position where we clicked
        self.last_click_file = None  # Last file we expect to be created
    
    def connect(self):
        """Connect to the Arduino controller."""
        logger.info("Connecting to Arduino...")
        self.connected = self.controller.connect()
        return self.connected
    
    def disconnect(self):
        """Disconnect from the Arduino controller."""
        if self.connected:
            logger.info("Disconnecting from Arduino...")
            self.controller.disconnect()
            self.connected = False
    
    def generate_grid(self, x_range=None, y_range=None, x_steps=None, y_steps=None, snake_pattern=None):
        """
        Generate a grid of scan points.
        
        Args:
            x_range: Tuple of (min_x, max_x) in motor steps
            y_range: Tuple of (min_y, max_y) in motor steps
            x_steps: Number of grid points in X direction
            y_steps: Number of grid points in Y direction
            snake_pattern: Whether to use snake pattern for more efficient scanning
        
        Returns:
            List of (x, y, x_idx, y_idx) points
        """
        # Use parameters from config if not specified
        x_range = x_range or self.config['x_range']
        y_range = y_range or self.config['y_range']
        x_steps = x_steps or self.config['x_steps']
        y_steps = y_steps or self.config['y_steps']
        snake_pattern = snake_pattern if snake_pattern is not None else self.config['snake_pattern']
        
        logger.info(f"Generating {x_steps}x{y_steps} grid scan...")
        logger.info(f"X range: {x_range}, Y range: {y_range}")
        
        # Generate grid points
        self.grid_points = []
        
        for y_idx in range(y_steps):
            y_pos = int(y_range[0] + (y_range[1] - y_range[0]) * y_idx / max(1, y_steps - 1))
            
            # Alternate direction for snake pattern
            if snake_pattern and y_idx % 2 == 1:
                x_indices = range(x_steps-1, -1, -1)
            else:
                x_indices = range(x_steps)
            
            for x_idx in x_indices:
                x_pos = int(x_range[0] + (x_range[1] - x_range[0]) * x_idx / max(1, x_steps - 1))
                self.grid_points.append((x_pos, y_pos, x_idx, y_idx))
        
        self.stats['total_points'] = len(self.grid_points)
        logger.info(f"Generated {len(self.grid_points)} grid points")
        
        return self.grid_points
    
    def generate_spiral_grid(self, x_range=None, y_range=None, x_steps=None, y_steps=None):
        """
        Generate a true spiral pattern for grid scanning that starts from the center
        and moves outward in a continuous path, covering the entire grid.
        """
        # Use parameters from config if not specified
        x_range = x_range or self.config['x_range']
        y_range = y_range or self.config['y_range']
        x_steps = x_steps or self.config['x_steps']
        y_steps = y_steps or self.config['y_steps']
        
        logger.info(f"Generating {x_steps}x{y_steps} spiral grid scan...")
        
        # Calculate step sizes
        x_step_size = (x_range[1] - x_range[0]) / max(1, x_steps - 1)
        y_step_size = (y_range[1] - y_range[0]) / max(1, y_steps - 1)
        
        # Create 2D array to track visited positions
        visited = [[False for _ in range(x_steps)] for _ in range(y_steps)]
        
        # Calculate true center (in grid indices)
        x_center_idx = x_steps // 2
        y_center_idx = y_steps // 2
        
        # Calculate center position in motor coordinates
        x_center_pos = int(x_range[0] + x_center_idx * x_step_size)
        y_center_pos = int(y_range[0] + y_center_idx * y_step_size)
        
        # Start at center
        grid_points = [(x_center_pos, y_center_pos, x_center_idx, y_center_idx)]
        visited[y_center_idx][x_center_idx] = True
        
        # Direction vectors: right, down, left, up
        dx = [1, 0, -1, 0]
        dy = [0, 1, 0, -1]
        
        # Current position (start at center)
        x, y = x_center_idx, y_center_idx
        
        # Current direction (0=right, 1=down, 2=left, 3=up)
        direction = 0
        
        # Continue until all grid points are visited
        total_points = x_steps * y_steps
        
        while len(grid_points) < total_points:
            # Try to move in current direction
            new_x = x + dx[direction]
            new_y = y + dy[direction]
            
            # Check if the new position is valid and not visited
            if (0 <= new_x < x_steps and 0 <= new_y < y_steps and not visited[new_y][new_x]):
                # Move to new position
                x, y = new_x, new_y
                
                # Add this position to grid points
                motor_x = int(x_range[0] + x * x_step_size)
                motor_y = int(y_range[0] + y * y_step_size)
                grid_points.append((motor_x, motor_y, x, y))
                
                # Mark as visited
                visited[y][x] = True
                
                # Try to turn left (spiral inward)
                left_direction = (direction + 1) % 4
                left_x = x + dx[left_direction]
                left_y = y + dy[left_direction]
                
                # If we can't move left, continue in current direction
                if not (0 <= left_x < x_steps and 0 <= left_y < y_steps and not visited[left_y][left_x]):
                    continue
                    
                # We can move left, so change direction
                direction = left_direction
            else:
                # Can't move in current direction, try turning right
                direction = (direction + 3) % 4  # +3 is equivalent to -1 in modular arithmetic
        
        # Assign grid points
        self.grid_points = grid_points
        self.stats['total_points'] = len(self.grid_points)
        
        logger.info(f"Generated {len(self.grid_points)} grid points in spiral pattern")
        return self.grid_points

    def configure_motors(self, speed_x=None, speed_y=None, accel_x=None, accel_y=None):
        """
        Configure motor parameters.
        
        Args:
            speed_x: X-axis motor speed
            speed_y: Y-axis motor speed
            accel_x: X-axis motor acceleration
            accel_y: Y-axis motor acceleration
            
        Returns:
            Success status
        """
        if not self.connected:
            logger.error("Not connected to Arduino. Call connect() first.")
            return False
        
        # Use parameters from config if not specified
        speed_x = speed_x or self.config['motor_speed_x']
        speed_y = speed_y or self.config['motor_speed_y']
        accel_x = accel_x or self.config['motor_accel_x']
        accel_y = accel_y or self.config['motor_accel_y']
        
        # Set operation mode to serial
        self.controller.set_mode(OperationMode.MODE_SERIAL)
        
        # Set speed and acceleration
        speed_result = self.controller.set_speed(speed_x, speed_y)
        accel_result = self.controller.set_acceleration(accel_x, accel_y)
        
        # Configure backlash compensation if applicable
        if 'backlash_compensation' in self.config and self.config['backlash_compensation']:
            backlash_x = self.config.get('backlash_x', 0)
            backlash_y = self.config.get('backlash_y', 0)
            if backlash_x > 0 or backlash_y > 0:
                backlash_result = self.controller.set_backlash_compensation(
                    backlash_x, backlash_y, enabled=True)
            else:
                backlash_result = True
        else:
            backlash_result = True
        
        # Enable motors
        enable_result = self.controller.enable_motors()
        
        return speed_result and accel_result and enable_result and backlash_result
    
    def _perform_click_only(self, x, y, x_idx, y_idx):
        """Just perform the click without waiting for file processing"""
        if not PYAUTOGUI_AVAILABLE or not MOUSE_CLICK_MODE:
            print("Mouse click mode is disabled or PyAutoGUI not available")
            return None
        
        click_success = False
        expected_file = None
        pyautogui.PAUSE = 0.01  # Set global PyAutoGUI delay to minimum
        
        try:
            # Get file count before click to determine expected new file
            initial_files = glob.glob(os.path.join(file_manager.base_capture_dir, "SpectrumFile_*.txt"))
            initial_count = len(initial_files)
            
            # Get current file number pattern to predict next file
            if initial_files:
                max_file_num = max([int(re.search(r'SpectrumFile_(\d+)\.txt', os.path.basename(f)).group(1)) 
                                for f in initial_files if re.search(r'SpectrumFile_(\d+)\.txt', os.path.basename(f))])
                expected_file = os.path.join(file_manager.base_capture_dir, f"SpectrumFile_{max_file_num+1}.txt")
            
            # Perform click
            click_x, click_y = MOUSE_CLICK_POSITION
            print(f"🖱️ CLICKING at position ({click_x}, {click_y}) for grid point ({x_idx}, {y_idx})")
            
            # Direct click without animation for speed
            pyautogui.moveTo(click_x, click_y, duration=PRE_CLICK_ANIMATION_DURATION)
            time.sleep(PRE_CLICK_DELAY)
            pyautogui.click(click_x, click_y)
            time.sleep(POST_CLICK_DELAY)
            
            click_success = True
            print(f"✅ Click completed for point ({x_idx}, {y_idx})")
            
            # Check if expected file can be determined
            if not expected_file:
                # Wait briefly for new file pattern to emerge
                time.sleep(0.2)
                new_files = glob.glob(os.path.join(file_manager.base_capture_dir, "SpectrumFile_*.txt"))
                new_files = [f for f in new_files if f not in initial_files]
                
                if new_files:
                    expected_file = new_files[0]
                else:
                    # Still can't determine exact file, use a wildcard pattern
                    expected_file = "NEXT_FILE"
            
            return {
                'click_success': click_success,
                'expected_file': expected_file,
                'position': (x, y),
                'grid_idx': (x_idx, y_idx)
            }
            
        except Exception as e:
            print(f"❌ ERROR during mouse click: {e}")
            return None

    def _process_pending_files(self):
        """Process any pending files that are ready"""
        if not self.pending_files:
            return
        
        files_to_remove = []
        
        for file_entry in self.pending_files:
            file_path, x_idx, y_idx = file_entry
            
            # Skip special placeholder
            if file_path == "NEXT_FILE":
                continue
                
            # Check if file exists and has content
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                print(f"Processing pending file {os.path.basename(file_path)} for point ({x_idx}, {y_idx})")
                
                # Process the file
                file_info = file_manager.process_capture_file(x_idx, y_idx, file_path)
                
                if file_info:
                    # Store successful capture
                    self.scan_data[(x_idx, y_idx)] = {
                        'position': (x_idx, y_idx),
                        'file_captured': True,
                        'file_info': file_info,
                        'timestamp': time.time()
                    }
                    self.stats['successful_captures'] += 1
                    
                    # Mark for removal from pending list
                    files_to_remove.append(file_entry)
                else:
                    print(f"Failed to process file for point ({x_idx}, {y_idx})")
        
        # Remove processed files from pending list
        for file_entry in files_to_remove:
            self.pending_files.remove(file_entry)

    def _process_all_pending_files(self):
        """Final sweep to process any remaining files"""
        # If we have a "NEXT_FILE" placeholder, try to find all new files
        for i, entry in enumerate(self.pending_files):
            file_path, x_idx, y_idx = entry
            if file_path == "NEXT_FILE":
                # Scan the directory for any new files
                all_files = glob.glob(os.path.join(file_manager.base_capture_dir, "SpectrumFile_*.txt"))
                # Sort by modification time (newest first)
                all_files.sort(key=os.path.getmtime)
                
                if all_files and len(all_files) > 0:
                    # Replace placeholder with actual file
                    self.pending_files[i] = (all_files[0], x_idx, y_idx)
        
        # Process remaining files with longer timeouts
        retry_count = 0
        while self.pending_files and retry_count < 3:
            initial_pending_count = len(self.pending_files)
            
            # Wait a bit longer for files to populate
            time.sleep(1.0)
            
            # Process what we can
            self._process_pending_files()
            
            # If no progress, increment retry counter
            if len(self.pending_files) == initial_pending_count:
                retry_count += 1
            else:
                retry_count = 0
        
        # Report on any files that couldn't be processed
        if self.pending_files:
            print(f"Warning: {len(self.pending_files)} files could not be processed:")
            for file_path, x_idx, y_idx in self.pending_files:
                print(f"  - Point ({x_idx}, {y_idx}): {os.path.basename(file_path)}")

    def perform_scan(self, data_callback, show_progress=True):
        """
        Perform the grid scan, calling the data callback at each point with asynchronous file processing.
        
        Args:
            data_callback: Function to call at each grid point
                        signature: callback(x, y, x_idx, y_idx) -> data
            show_progress: Whether to show progress information
            
        Returns:
            (success, scan_data) tuple
        """
        if not self.connected:
            logger.error("Not connected to Arduino. Call connect() first.")
            return False, {}
        
        if not self.grid_points:
            logger.error("No grid points defined. Call generate_grid() first.")
            return False, {}
        
        logger.info(f"Starting grid scan with {len(self.grid_points)} points")
        
        # Reset statistics
        self.stats['points_completed'] = 0
        self.stats['successful_captures'] = 0
        self.stats['failed_captures'] = 0
        self.stats['retried_points'] = 0
        self.stats['skipped_points'] = 0
        self.stats['start_time'] = time.time()
        self.stats['data_collection_time'] = 0
        self.stats['movement_time'] = 0
        self.stats['file_processing_time'] = 0
        
        # Reset data storage
        self.scan_data = {}
        self.failed_points = []
        self.pending_files = []  # [(file_path, x_idx, y_idx), ...]
        self.last_click_position = None
        self.last_click_file = None
        
        # Configure motors
        if not self.configure_motors():
            logger.error("Failed to configure motors")
            return False, {}
        
        try:
            # Process each grid point
            for i, (x, y, x_idx, y_idx) in enumerate(self.grid_points):
                # Update current index
                self.current_index = i
                
                # First, process any pending files while we're moving
                with TimingContext(self, 'file_processing_time'):
                    self._process_pending_files()
                
                # Show progress
                if show_progress:
                    completed = i
                    total = len(self.grid_points)
                    percent = (completed / total * 100) if total > 0 else 0
                    
                    # Calculate ETA
                    elapsed = time.time() - self.stats['start_time']
                    if completed > 0 and elapsed > 0:
                        points_per_sec = completed / elapsed
                        remaining = (total - completed) / points_per_sec if points_per_sec > 0 else 0
                        
                        print(f"\rProgress: {completed}/{total} points " +
                            f"({percent:.1f}%) - " +
                            f"Captures: {self.stats['successful_captures']}/{completed} - " +
                            f"ETA: {int(remaining/60)}m {int(remaining%60)}s - " +
                            f"Pending files: {len(self.pending_files)}", end="")
                
                # Move to the grid point
                movement_start = time.time()
                
                # Queue movement with point_data
                sequence_id = self.controller.queue_movement(x, y, {'x_idx': x_idx, 'y_idx': y_idx})
                
                if sequence_id == 0:
                    logger.error(f"Failed to move to grid point ({x}, {y})")
                    continue
                
                # Wait for position notification
                position = self.controller.wait_for_position(
                    sequence_id, 
                    timeout=self.config['movement_timeout']
                )
                
                # Update movement time
                self.stats['movement_time'] += time.time() - movement_start
                
                if position:
                    # Position reached, add stabilization delay
                    time.sleep(self.config['stabilization_delay'])
                else:
                    logger.warning(f"No position notification for grid point ({x}, {y})")
                    
                    # Check current position through status
                    status = self.controller.get_status()
                    if not status:
                        logger.error("Failed to get status after movement")
                        continue
                    
                    # Check if position is close enough
                    current_x = status['x_position']
                    current_y = status['y_position']
                    
                    if (abs(current_x - x) > self.config['position_tolerance'] or
                        abs(current_y - y) > self.config['position_tolerance']):
                        logger.warning(f"Position mismatch: Current ({current_x}, {current_y}), " +
                                    f"Target ({x}, {y})")
                
                # Now perform the click without waiting for file
                data_start = time.time()
                click_result = self._perform_click_only(x, y, x_idx, y_idx)
                
                if click_result and click_result.get('click_success', False):
                    # Add expected file to pending list if available
                    if 'expected_file' in click_result and click_result['expected_file']:
                        expected_file = click_result['expected_file']
                        self.pending_files.append((expected_file, x_idx, y_idx))
                        self.last_click_position = (x, y, x_idx, y_idx)
                        self.last_click_file = expected_file
                        
                        # Add placeholder entry in scan data
                        self.scan_data[(x_idx, y_idx)] = {
                            'position': (x, y),
                            'grid_idx': (x_idx, y_idx),
                            'timestamp': time.time(),
                            'pending_processing': True,
                            'processed': False
                        }
                    else:
                        # Could not determine expected file, add a placeholder
                        placeholder = "NEXT_FILE"
                        self.pending_files.append((placeholder, x_idx, y_idx))
                        self.last_click_position = (x, y, x_idx, y_idx)
                        self.last_click_file = placeholder
                else:
                    # Click failed
                    logger.warning(f"Failed to click at grid point ({x_idx}, {y_idx})")
                    self.stats['failed_captures'] += 1
                    self.failed_points.append((x, y, x_idx, y_idx))
                
                # Update data collection time
                self.stats['data_collection_time'] += time.time() - data_start
                
                # Update completed points count
                self.stats['points_completed'] += 1
            
            if show_progress:
                print()  # New line after progress
            
            # Process any remaining files
            logger.info("Processing remaining files...")
            self._process_all_pending_files()
            
            # Move back to home position (0, 0)
            logger.info("Scan complete, moving to home position")
            self.controller.queue_movement(0, 0)
            
            # Calculate final statistics
            elapsed = time.time() - self.stats['start_time']
            if elapsed > 0 and self.stats['points_completed'] > 0:
                self.stats['points_per_second'] = self.stats['points_completed'] / elapsed
            
            # Print comprehensive statistics
            logger.info(f"Scan completed in {elapsed:.2f} seconds")
            logger.info(f"Points completed: {self.stats['points_completed']}/{self.stats['total_points']}")
            logger.info(f"Successful captures: {self.stats['successful_captures']}/{self.stats['points_completed']} ({self.stats['successful_captures']/self.stats['points_completed']*100:.1f}%)")
            logger.info(f"Failed captures: {self.stats['failed_captures']}")
            logger.info(f"Points retried: {self.stats['retried_points']}")
            logger.info(f"Points skipped: {self.stats['skipped_points']}")
            logger.info(f"Average rate: {self.stats['points_per_second']:.2f} points/second")
            
            self._show_timing_summary()
            
            return True, self.scan_data
            
        except Exception as e:
            logger.error(f"Error during scan: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            
            return False, self.scan_data
        
        finally:
            # Make sure motors are disabled when done
            try:
                self.controller.disable_motors()
            except:
                pass
            
    def move_to_next_point(self, data_callback=None):
        """
        Move to the next grid point in sequence.
        
        Args:
            data_callback: Optional callback function for data collection
        
        Returns:
            (x, y, x_idx, y_idx) of the new position, or None if no more points
        """
        if not self.connected:
            logger.error("Not connected to Arduino. Call connect() first.")
            return None
        
        if not self.grid_points:
            logger.error("No grid points defined. Call generate_grid() first.")
            return None
        
        # Calculate next index
        next_index = self.current_index + 1
        
        if next_index >= len(self.grid_points):
            logger.info("No more grid points")
            return None
        
        # Get next grid point
        x, y, x_idx, y_idx = self.grid_points[next_index]
        
        # Move to the point
        sequence_id = self.controller.queue_movement(x, y, {'x_idx': x_idx, 'y_idx': y_idx})
        
        if sequence_id == 0:
            logger.error(f"Failed to move to grid point ({x}, {y})")
            return None
        
        # Wait for position notification
        position = self.controller.wait_for_position(
            sequence_id, 
            timeout=self.config['movement_timeout']
        )
        
        if position:
            # Position reached, add stabilization delay
            time.sleep(self.config['stabilization_delay'])
        else:
            logger.warning(f"No position notification for grid point ({x}, {y})")
            
            # Check current position through status
            status = self.controller.get_status()
            if not status:
                logger.error("Failed to get status after movement")
                return None
            
            # Check if position is close enough
            current_x = status['x_position']
            current_y = status['y_position']
            
            if (abs(current_x - x) > self.config['position_tolerance'] or
                abs(current_y - y) > self.config['position_tolerance']):
                logger.warning(f"Position mismatch: Current ({current_x}, {current_y}), " +
                              f"Target ({x}, {y})")
        
        # Update current index
        self.current_index = next_index
        
        # Call data callback if provided
        if data_callback:
            try:
                point_data = data_callback(x, y, x_idx, y_idx)
                
                # Store data with grid indices as key
                self.scan_data[(x_idx, y_idx)] = point_data
                
                # Update statistics
                if 'file_captured' in point_data and point_data['file_captured']:
                    self.stats['successful_captures'] += 1
                else:
                    self.stats['failed_captures'] += 1
                
            except Exception as e:
                logger.error(f"Error in data collection callback: {e}")
                self.stats['failed_captures'] += 1
        
        return (x, y, x_idx, y_idx)
    
    def get_stats(self):
        """Get scan statistics."""
        return self.stats.copy()
    
    def move_to_home(self):
        """Move to home position (0, 0)."""
        if not self.connected:
            logger.error("Not connected to Arduino. Call connect() first.")
            return False
        
        logger.info("Moving to home position")
        sequence_id = self.controller.queue_movement(0, 0)
        
        if sequence_id == 0:
            logger.error("Failed to move to home position")
            return False
        
        # Wait for position notification
        position = self.controller.wait_for_position(
            sequence_id, 
            timeout=self.config['movement_timeout']
        )
        
        return position is not None
    
    def step_scan_interactive(self, data_callback=None):
        """
        Run an interactive step-by-step scan where the user
        triggers movement to the next point.
        
        Args:
            data_callback: Optional callback function for data collection
                          signature: callback(x, y, x_idx, y_idx) -> data
        
        Returns:
            scan_data dictionary
        """
        if not self.connected:
            logger.error("Not connected to Arduino. Call connect() first.")
            return {}
        
        if not self.grid_points:
            logger.error("No grid points defined. Call generate_grid() first.")
            return {}
        
        # Configure motors
        if not self.configure_motors():
            logger.error("Failed to configure motors")
            return {}
        
        # Reset scan state
        self.current_index = -1
        self.scan_data = {}
        self.stats['points_completed'] = 0
        self.stats['successful_captures'] = 0
        self.stats['failed_captures'] = 0
        self.stats['start_time'] = time.time()
        
        print("\nInteractive Step Scan")
        print("---------------------")
        print(f"Grid size: {self.config['x_steps']}x{self.config['y_steps']}")
        print(f"Total points: {len(self.grid_points)}")
        print("Press Enter to move to the next point...")
        print("Press Ctrl+C to abort")
        
        try:
            while True:
                # Move to next point
                next_point = self.move_to_next_point(data_callback)
                
                if not next_point:
                    print("\nScan complete! All points processed.")
                    break
                
                x, y, x_idx, y_idx = next_point
                
                # Display info
                print(f"\nPoint {self.current_index + 1}/{len(self.grid_points)}")
                print(f"Position: ({x}, {y})")
                print(f"Grid index: ({x_idx}, {y_idx})")
                
                if data_callback:
                    print("Data collected.")
                    
                    # Check if capture was successful
                    data = self.scan_data.get((x_idx, y_idx), {})
                    if 'file_captured' in data:
                        if data['file_captured']:
                            print("✅ Capture successful")
                        else:
                            print("❌ Capture failed")
                            
                            # Ask user if they want to retry
                            retry = input("Retry capture? (y/n): ").lower() == 'y'
                            if retry:
                                print("Retrying capture...")
                                point_data = data_callback(x, y, x_idx, y_idx)
                                self.scan_data[(x_idx, y_idx)] = point_data
                
                # Wait for user input to continue
                input("Press Enter to continue to next point...")
            
            # Move back to home
            self.move_to_home()
            
        except KeyboardInterrupt:
            print("\nScan aborted by user.")
        
        finally:
            # Make sure motors are disabled when done
            try:
                self.controller.disable_motors()
            except:
                pass
        
        # Return collected data
        return self.scan_data

class TimingContext:
    """Context manager for timing operations"""
    
    def __init__(self, scanner, category):
        self.scanner = scanner
        self.category = category
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        
        # Update global stats
        self.scanner.stats[self.category] += elapsed
        
        # Update current point timing
        if self.category in self.scanner.current_point_timing:
            self.scanner.current_point_timing[self.category] += elapsed
        else:
            self.scanner.current_point_timing[self.category] = elapsed
        
        # If verbose timing is enabled, print timing information
        if TIMING_VERBOSE and elapsed > 0.1:  # Only show significant times
            print(f"  {self.category}: {elapsed:.3f}s")

# Print usage instructions
def print_usage():
    print("\nGrid Scanner Program")
    print("------------------")
    print("This program performs grid scans using an Arduino-controlled motor system.")
    print("\nUsage:")
    print(f"  python scanner.py [COM_PORT] [interactive|mouseclick|skipfailed]")
    print("\nArguments:")
    print(f"  COM_PORT      Serial port (default: {COM_PORT})")
    print(f"  interactive   Run in step-by-step mode")
    print(f"  mouseclick    Enable mouse click mode")
    print(f"  skipfailed    Skip failed capture points")
    print("\nExamples:")
    print(f"  python scanner.py                  # Run automatic scan using default COM port")
    print(f"  python scanner.py COM3             # Run automatic scan using COM3 port")
    print(f"  python scanner.py interactive      # Run interactive scan using default COM port")
    print(f"  python scanner.py COM3 mouseclick  # Run automatic scan with mouse click capture")
    
    print("\nCurrent Configuration:")
    print(f"  Grid: {X_STEPS}x{Y_STEPS} points")
    print(f"  X Range: {X_RANGE[0]}-{X_RANGE[1]} steps")
    print(f"  Y Range: {Y_RANGE[0]}-{Y_RANGE[1]} steps")
    print(f"  Motor Speed: X={MOTOR_SPEED_X}, Y={MOTOR_SPEED_Y} steps/sec")
    print(f"  Motor Accel: X={MOTOR_ACCEL_X}, Y={MOTOR_ACCEL_Y} steps/sec²")
    print("\nTo modify these settings, edit the parameters at the top of this file.")


def run_test_scan():
    """Run a test scan with the grid scanner."""
    
    # Check if COM port is specified on command line (overrides config setting)
    port = COM_PORT
    if len(sys.argv) > 1 and not sys.argv[1].lower() in ["interactive", "mouseclick", "skipfailed"]:
        port = sys.argv[1]
    
    # Check for special modes
    interactive_mode = any(arg.lower() == 'interactive' for arg in sys.argv)
    mouse_click_mode = any(arg.lower() == 'mouseclick' for arg in sys.argv)
    skip_failed_mode = any(arg.lower() == 'skipfailed' for arg in sys.argv)
    
    # Also respect the code setting if command line isn't specified
    if not mouse_click_mode:
        mouse_click_mode = MOUSE_CLICK_MODE
    
    print(f"Using COM port: {port}")
    print(f"Mode: {'Interactive' if interactive_mode else 'Automatic'}")
    print(f"Mouse Click Mode: {'Enabled' if mouse_click_mode else 'Disabled'}")
    print(f"Skip Failed Captures: {'Enabled' if skip_failed_mode else 'Disabled'}")
    
    # Create scanner with custom config if needed
    config = {
        'mouse_click_mode': mouse_click_mode,
        'skip_failed_captures': skip_failed_mode,
        'mouse_click_position': MOUSE_CLICK_POSITION
    }
    
    print(f"Mouse Click Settings:")
    print(f"  - Mode: {config['mouse_click_mode']}")
    print(f"  - Position: {config['mouse_click_position']}")
    print(f"  - Delay: {POST_CLICK_DELAY} seconds")
    
    # Initialize file manager for this scan
    scan_name = input("Enter a name for this scan (or press Enter for auto-name): ")
    scan_id = file_manager.start_new_scan(scan_name or None)
    print(f"Starting scan: {scan_id}")
    
    # Create scanner
    scanner = GridScanner(port, config=config, verbose=VERBOSE_OUTPUT)
    
    # Connect to Arduino
    if not scanner.connect():
        print(f"Failed to connect to Arduino on {port}")
        return
    
    # Generate grid
    scanner.generate_spiral_grid()  # Parameters from config
    
    # Choose collection function based on mode
    if mouse_click_mode:
        collection_func = mouse_click_data_collection
        print(f"Using mouse click data collection function")
    else:
        collection_func = standard_data_collection
        print(f"Using standard data collection function")
    
    # Ask user to prepare application window
    print("\nPreparing to start scan...")
    print("Please ensure your target application window is visible and ready.")
    countdown = DEFAULT_SCAN_COUNTDOWN
    for i in range(countdown, 0, -1):
        print(f"Starting in {i} seconds...", end="\r")
        time.sleep(1)
    print("\nStarting scan now!                ")
    
    # Run scan based on mode
    start_time = time.time()
    
    if interactive_mode:
        # Interactive step-by-step scan
        scan_data = scanner.step_scan_interactive(collection_func)
    else:
        # Automatic scan
        success, scan_data = scanner.perform_scan(collection_func, show_progress=True)
    
    elapsed_time = time.time() - start_time
    
    if success or interactive_mode:
        # Count successful captures
        captures = sum(1 for data in scan_data.values() if data.get('file_captured', True))
        total = len(scan_data)
        
        print(f"\nScan completed in {elapsed_time:.2f} seconds")
        print(f"Successful captures: {captures}/{total} ({captures/total*100:.1f}% success rate)")
        
        # Write metadata about the scan
        metadata_file = os.path.join(file_manager.current_scan_dir, "scan_metadata.txt")
        with open(metadata_file, 'w') as f:
            f.write(f"Scan ID: {scan_id}\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Duration: {elapsed_time:.2f} seconds\n")
            f.write(f"Grid: {scanner.config['x_steps']}x{scanner.config['y_steps']}\n")
            f.write(f"Successful captures: {captures}/{total} ({captures/total*100:.1f}%)\n")
            f.write(f"X Range: {scanner.config['x_range']}\n")
            f.write(f"Y Range: {scanner.config['y_range']}\n")
            f.write(f"Motor Speed: X={scanner.config['motor_speed_x']}, Y={scanner.config['motor_speed_y']}\n")
            f.write(f"Motor Accel: X={scanner.config['motor_accel_x']}, Y={scanner.config['motor_accel_y']}\n")
            f.write(f"Snake Pattern: {scanner.config['snake_pattern']}\n")
            
            # Write statistics
            f.write("\nStatistics:\n")
            stats = scanner.get_stats()
            for key, value in stats.items():
                f.write(f"  {key}: {value}\n")
            
            # Write failed points if any
            if scanner.failed_points:
                f.write("\nFailed Points:\n")
                for x, y, x_idx, y_idx in scanner.failed_points:
                    f.write(f"  Position: ({x}, {y}), Grid: ({x_idx}, {y_idx})\n")
        
        print(f"Scan data organized in: {file_manager.current_scan_dir}")
        print(f"Scan metadata saved to: {metadata_file}")
    else:
        print("\nScan failed")


if __name__ == "__main__":
    # Check for help argument
    if any(arg in ['--help', '-h', 'help', '/?'] for arg in sys.argv):
        print_usage()
    else:
        run_test_scan()