#!/usr/bin/env python3
"""
Mouse Position Finder Utility (Improved for PowerShell)

This utility helps you find the screen coordinates where you want the mouse to click
during scanning operations.

Usage:
    python mouse_position.py
"""

import time
import sys

# Check for PyAutoGUI
try:
    import pyautogui
    print("PyAutoGUI successfully imported.")
except ImportError:
    print("ERROR: PyAutoGUI not installed.")
    print("Please install with: pip install pyautogui")
    sys.exit(1)

def main():
    """Run the mouse position utility"""
    print("\nMouse Position Finder")
    print("--------------------")
    print("Move your mouse to the position where you want clicks to occur.")
    print("Position updates every second.")
    print("Press Ctrl+C to exit and copy the position.\n")
    
    try:
        while True:
            # Get current position
            x, y = pyautogui.position()
            
            # Print with a newline instead of \r for PowerShell compatibility
            print(f"Current position: ({x}, {y})     ")
            
            # Sleep to reduce updates and CPU usage
            time.sleep(1)
    
    except KeyboardInterrupt:
        # Print final position
        x, y = pyautogui.position()
        print(f"\nFinal position: ({x}, {y})")
        print(f"\nUse this position in scanner.py as:")
        print(f"MOUSE_CLICK_POSITION = ({x}, {y})")
        print(f"\nOr run scanner with:")
        print(f"python scanner.py mouseclick mousepos={x},{y}\n")

if __name__ == "__main__":
    # Add a simple debug message to ensure script is running
    print("Script started. If you see this, the script is running correctly.")
    main()