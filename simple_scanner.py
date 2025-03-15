"""
Enhanced Scanner Controller with Safety Features

This module provides a robust and safe scanner implementation using the WorkingMotorController.
It includes features like automatic motor disabling, scan resumption, and proper error handling.
"""
import time
import logging
import atexit
from typing import Tuple, Dict, Optional, Union, List, Callable
from motor_controller import ImprovedMotorController, OperationMode

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Change from DEBUG to INFO for less verbose logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scanner.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("EnhancedScanner")

# Default configuration parameters
DEFAULT_CONFIG = {
    # Motor Movement Parameters
    'motor_speed_x': 600,              # Default X-axis motor speed
    'motor_speed_y': 600,              # Default Y-axis motor speed
    'motor_accel_x': 1000,             # Default X-axis acceleration
    'motor_accel_y': 1000,             # Default Y-axis acceleration
    
    # Scan Parameters
    'default_x_range': (0, 100),       # Default X scan range in steps
    'default_y_range': (0, 100),       # Default Y scan range in steps
    'default_x_steps': 5,              # Default number of X steps in scan
    'default_y_steps': 5,              # Default number of Y steps in scan

    # Timing Parameters
    'stabilization_delay': 0.1,        # Delay after motion for stabilization (seconds)
    'movement_timeout': 10.0,          # Timeout for movements (seconds)
    
    # Error Handling Parameters
    'position_tolerance': 3,           # Tolerance for position verification (steps)
    'retry_attempts': 3,               # Number of retry attempts for failed operations
    'recovery_enabled': True,          # Whether to attempt recovery from errors
    
    # Safety Parameters
    'auto_disable_on_exit': True,      # Automatically disable motors on exit
    'auto_return_to_joystick': True,   # Automatically return to joystick mode on exit
}

class EnhancedScanner:
    """
    Enhanced scanner controller with safety features
    """
    
    def __init__(self, port: str, config: Optional[Dict] = None):
        """
        Initialize the scanner controller.
        
        Args:
            port: Serial port for the motor controller
            config: Optional configuration dictionary
        """
        self.motor_controller = ImprovedMotorController(port)
        self.connection_status = False
        
        # Initialize with default config, then update with any provided config
        self.config = DEFAULT_CONFIG.copy()
        if config:
            self.configure(config)
        
        # For tracking scan progress
        self.scan_progress = {
            'completed_points': 0,
            'total_points': 0,
            'current_position': (0, 0),
            'points_done': []
        }
        
        # Scan parameters
        self.scan_params = {
            'x_range': (0, 0),
            'y_range': (0, 0),
            'x_steps': 0,
            'y_steps': 0
        }
        
        # Error and recovery statistics
        self.error_stats = {
            'communication_errors': 0,
            'positioning_errors': 0,
            'recovery_attempts': 0,
            'successful_recoveries': 0
        }
        
        # Configure motor controller safety features
        self.motor_controller.auto_disable_on_disconnect = self.config['auto_disable_on_exit']
        self.motor_controller.auto_switch_to_joystick = self.config['auto_return_to_joystick']
        
        # Register safe shutdown
        atexit.register(self.safe_shutdown)
    
    def safe_shutdown(self):
        """Safely shut down the scanner"""
        if self.connection_status:
            logger.info("Performing safe scanner shutdown...")
        
        try:
            # Stop any ongoing movement first
            try:
                self.motor_controller.stop()
                time.sleep(0.5)  # Short delay after stopping
            except Exception as e:
                logger.warning(f"Error stopping motors: {e}")
            
            # CHANGED ORDER: Disable motors before mode change
            try:
                logger.info("Disabling motors during scanner shutdown")
                self.motor_controller.disable_motors()
                time.sleep(1.0)  # Longer delay after disabling
            except Exception as e:
                logger.warning(f"Error disabling motors: {e}")
            
            # Switch to joystick mode after motors are disabled
            try:
                logger.info("Switching to joystick mode during scanner shutdown")
                self.motor_controller.set_mode(OperationMode.MODE_JOYSTICK)
                time.sleep(0.5)  # Short delay after mode change
            except Exception as e:
                logger.warning(f"Error switching mode: {e}")
            
            # Flush any pending communication
            try:
                self.motor_controller.flush_buffers()
            except Exception as e:
                logger.warning(f"Error flushing buffers: {e}")
            
            # Finally disconnect
            self.disconnect()
            
        except Exception as e:
            logger.error(f"Error during safe scanner shutdown: {e}")
    
    def _safe_shutdown_after_scan(self):
        """Safely shutdown motors after scan completion"""
        try:
            # Use a very careful shutdown sequence
            logger.info("Performing scan completion shutdown")
            
            # First stop any movement
            try:
                self.motor_controller.stop()
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Error stopping motors: {e}")
            
            # Disable motors while still in serial mode
            try:
                self.motor_controller.disable_motors()
                time.sleep(1.0)
            except Exception as e:
                logger.warning(f"Error disabling motors: {e}")
            
            # Switch to joystick mode last
            try:
                self.motor_controller.set_mode(OperationMode.MODE_JOYSTICK)
            except Exception as e:
                logger.warning(f"Error switching mode: {e}")
        except Exception as e:
            logger.error(f"Error during scan shutdown: {e}")

    def configure(self, config_dict: Optional[Dict] = None, **kwargs) -> None:
        """
        Update configuration parameters.
        
        Args:
            config_dict: Dictionary of configuration parameters
            **kwargs: Configuration parameters as keyword arguments
        """
        # Handle dictionary style updates
        if config_dict:
            for key, value in config_dict.items():
                if key in self.config:
                    self.config[key] = value
                    logger.info(f"Updated config: {key} = {value}")
                    
                    # Update motor controller if relevant
                    if key == 'auto_disable_on_exit':
                        self.motor_controller.auto_disable_on_disconnect = value
                    elif key == 'auto_return_to_joystick':
                        self.motor_controller.auto_switch_to_joystick = value
                else:
                    logger.warning(f"Unknown config parameter: {key}")
        
        # Handle keyword style updates
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
                logger.info(f"Updated config: {key} = {value}")
                
                # Update motor controller if relevant
                if key == 'auto_disable_on_exit':
                    self.motor_controller.auto_disable_on_disconnect = value
                elif key == 'auto_return_to_joystick':
                    self.motor_controller.auto_switch_to_joystick = value
            else:
                logger.warning(f"Unknown config parameter: {key}")
    
    def connect(self) -> bool:
        """
        Connect to the motor controller.
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        try:
            logger.info("Connecting to motor controller...")
            
            if self.motor_controller.connect():
                logger.info("Connected to motor controller")
                self.connection_status = True
                return True
            else:
                logger.warning("Connection failed")
                return False
                
        except Exception as e:
            logger.error(f"Error during connection: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the motor controller."""
        logger.info("Disconnecting from motor controller...")
        try:
            self.motor_controller.disconnect()
            self.connection_status = False
            logger.info("Disconnected successfully")
        except Exception as e:
            logger.error(f"Error during disconnection: {e}")
    
    def initialize_scan(self, x_range: Optional[Tuple[int, int]] = None, 
                        y_range: Optional[Tuple[int, int]] = None, 
                        x_steps: Optional[int] = None, 
                        y_steps: Optional[int] = None) -> bool:
        """
        Initialize the scanner for a scan.
        
        Args:
            x_range: Tuple of (min_x, max_x) in motor steps
            y_range: Tuple of (min_y, max_y) in motor steps
            x_steps: Number of points in X direction
            y_steps: Number of points in Y direction
            
        Returns:
            bool: True if initialized successfully, False otherwise
        """
        # Use provided values or defaults
        x_range = x_range or self.config['default_x_range']
        y_range = y_range or self.config['default_y_range']
        x_steps = x_steps or self.config['default_x_steps']
        y_steps = y_steps or self.config['default_y_steps']
        
        logger.info(f"Initializing scan with {x_steps}x{y_steps} points")
        
        # Save scan parameters
        self.scan_params = {
            'x_range': x_range,
            'y_range': y_range,
            'x_steps': x_steps,
            'y_steps': y_steps
        }
        
        # Check connection
        if not self.connection_status:
            logger.warning("Not connected to motor controller. Attempting to connect...")
            if not self.connect():
                logger.error("Failed to connect to motor controller")
                return False
        
        # Switch to serial control mode
        if not self.motor_controller.set_mode(OperationMode.MODE_SERIAL):
            logger.error("Failed to switch to serial mode")
            return False
        
        # Enable motors
        if not self.motor_controller.enable_motors():
            logger.error("Failed to enable motors")
            return False
        
        # Set motor speeds
        if not self.motor_controller.set_speed(self.config['motor_speed_x'], 
                                            self.config['motor_speed_y']):
            logger.error("Failed to set motor speeds")
            return False
        
        # Set motor acceleration
        if not self.motor_controller.set_acceleration(self.config['motor_accel_x'], 
                                                   self.config['motor_accel_y']):
            logger.error("Failed to set motor acceleration")
            return False
        
        # Home the motors to set zero position
        if not self.motor_controller.home():
            logger.error("Failed to home motors")
            return False
        
        # Update scan progress tracking
        self.scan_progress = {
            'completed_points': 0,
            'total_points': x_steps * y_steps,
            'current_position': (0, 0),
            'points_done': []  # List to track which points we've completed
        }
        
        logger.info("Scan initialized successfully")
        return True
    
    def move_to_position(self, target_x: int, target_y: int, 
                    max_attempts: int = None) -> bool:
        """Move to position with optimized approach"""
        if max_attempts is None:
            max_attempts = self.config['retry_attempts']
        
        # Now that motor enabling is handled in ImprovedMotorController.move_to,
        # we don't need to do it here anymore
        
        for attempt in range(max_attempts):
            # Send move command with the improved non-blocking approach
            if self.motor_controller.move_to(target_x, target_y):
                # Success, position reached
                return True
            
            logger.warning(f"Retry {attempt+1}/{max_attempts} to position ({target_x}, {target_y})")
            
            # Last attempt - try recovery
            if attempt == max_attempts - 1 and self.config['recovery_enabled']:
                logger.info("Attempting position recovery")
                self.error_stats['recovery_attempts'] += 1
                
                if self._attempt_recovery(target_x, target_y):
                    self.error_stats['successful_recoveries'] += 1
                    return True
        
        self.error_stats['positioning_errors'] += 1
        return False
    
    def _attempt_recovery(self, target_x: int, target_y: int) -> bool:
        """
        Attempt to recover from positioning errors.
        
        Args:
            target_x: Target X position
            target_y: Target Y position
            
        Returns:
            bool: True if recovery was successful, False otherwise
        """
        try:
            # Stop all motors first
            self.motor_controller.stop()
            time.sleep(0.5)
            
            # Try a soft reset approach
            
            # 1. Re-enable motors
            self.motor_controller.enable_motors()
            time.sleep(0.5)
            
            # 2. Reset speed and acceleration
            self.motor_controller.set_speed(
                self.config['motor_speed_x'] // 2,  # Slower speed for recovery
                self.config['motor_speed_y'] // 2
            )
            
            self.motor_controller.set_acceleration(
                self.config['motor_accel_x'] // 2,  # Gentler acceleration
                self.config['motor_accel_y'] // 2
            )
            
            # 3. Try to move to current position first (to recalibrate)
            current_x, current_y = self.motor_controller.get_position()
            if current_x is not None and current_y is not None:
                # Small move to reset motors
                self.motor_controller.move_by(10, 10)
                time.sleep(0.5)
                self.motor_controller.move_by(-10, -10)
                time.sleep(0.5)
            
            # 4. Now try to move to target again
            if self.motor_controller.move_to(target_x, target_y):
                # Wait with extended timeout
                extended_timeout = self.config['movement_timeout'] * 1.5
                if self.motor_controller.wait_for_position(
                    target_x, 
                    target_y, 
                    timeout=extended_timeout,
                    tolerance=self.config['position_tolerance'] * 2  # More lenient tolerance
                ):
                    logger.info(f"Recovery successful - reached position ({target_x}, {target_y})")
                    
                    # Reset speed and acceleration to normal
                    self.motor_controller.set_speed(
                        self.config['motor_speed_x'],
                        self.config['motor_speed_y']
                    )
                    
                    self.motor_controller.set_acceleration(
                        self.config['motor_accel_x'],
                        self.config['motor_accel_y']
                    )
                    
                    return True
            
            logger.warning("Recovery with soft reset failed, attempting re-home")
            
            # More drastic recovery - re-home and try again
            if self.motor_controller.home():
                time.sleep(1.0)  # Longer pause after homing
                
                # Try one more time to reach target
                if self.motor_controller.move_to(target_x, target_y):
                    if self.motor_controller.wait_for_position(
                        target_x, 
                        target_y, 
                        timeout=extended_timeout,
                        tolerance=self.config['position_tolerance']
                    ):
                        logger.info(f"Recovery with re-home successful - reached position ({target_x}, {target_y})")
                        
                        # Reset speed and acceleration to normal
                        self.motor_controller.set_speed(
                            self.config['motor_speed_x'],
                            self.config['motor_speed_y']
                        )
                        
                        self.motor_controller.set_acceleration(
                            self.config['motor_accel_x'],
                            self.config['motor_accel_y']
                        )
                        
                        return True
            
            logger.error("All recovery attempts failed")
            return False
            
        except Exception as e:
            logger.error(f"Error during recovery: {e}")
            return False
    
    def perform_scan(self, delay: Optional[float] = None, show_progress: bool = True, 
                    resume: bool = False, data_callback: Optional[Callable] = None) -> bool:
        """
        Perform the scan operation with optimized movement pattern
        """
        if not self.scan_params['x_steps'] or not self.scan_params['y_steps']:
            logger.error("Scan not initialized. Call initialize_scan first.")
            return False
        
        if delay is None:
            delay = self.config['stabilization_delay']
        
        # Get scan parameters
        x_steps = self.scan_params['x_steps']
        y_steps = self.scan_params['y_steps']
        x_range = self.scan_params['x_range']
        y_range = self.scan_params['y_range']
        
        total_points = x_steps * y_steps
        self.scan_progress['total_points'] = total_points
        
        # If not resuming, reset progress
        if not resume:
            self.scan_progress['completed_points'] = 0
            self.scan_progress['points_done'] = []
        
        processed_points = self.scan_progress['completed_points']
        points_done = set(self.scan_progress['points_done'])
        
        start_time = time.time()
        
        logger.info(f"Starting scan with {x_steps}x{y_steps} points")
        
        try:
            # Do one-time setup at the beginning
            self.motor_controller.set_mode(OperationMode.MODE_SERIAL)
            self.motor_controller.enable_motors()
            time.sleep(0.5)  # Short pause to let motors initialize
            
            # IMPROVED: Use a more efficient scanning pattern that minimizes long moves
            # Snake pattern with optimized order
            last_position = None
            
            # Generate optimized scan pattern coordinates
            scan_positions = []
            for y_idx in range(y_steps):
                row_positions = []
                for x_idx in range(x_steps):
                    # Calculate actual positions
                    x_pos = int(x_range[0] + (x_range[1] - x_range[0]) * x_idx / max(1, x_steps - 1))
                    y_pos = int(y_range[0] + (y_range[1] - y_range[0]) * y_idx / max(1, y_steps - 1))
                    row_positions.append((x_pos, y_pos, x_idx, y_idx))
                
                # Reverse every other row for snake pattern
                if y_idx % 2 == 1:
                    row_positions.reverse()
                    
                scan_positions.extend(row_positions)
            
            # Optimize for points already done when resuming
            if resume and points_done:
                scan_positions = [pos for pos in scan_positions 
                                if (pos[3], pos[2]) not in points_done]
            
            total_points = len(scan_positions)
            processed_points = 0
            
            # Perform the scan using the optimized pattern
            for x_pos, y_pos, x_idx, y_idx in scan_positions:
                logger.info(f"Moving to position ({x_pos}, {y_pos})")
                
                # Move to position with improved error handling
                move_success = self.move_to_position(x_pos, y_pos)
                
                if not move_success:
                    logger.error(f"Failed to move to position ({x_pos}, {y_pos})")
                    self.scan_progress['current_position'] = (y_idx, x_idx)
                    return False
                
                # Get actual position
                actual_x, actual_y = self.motor_controller.get_position()
                logger.info(f"Position reached: X={actual_x}, Y={actual_y}")
                
                # Additional delay for stability if provided
                if delay > 0:
                    time.sleep(delay)
                
                # Data acquisition
                if data_callback:
                    logger.info(f"Acquiring data at position ({x_pos}, {y_pos})")
                    pos_x = actual_x if actual_x is not None else x_pos
                    pos_y = actual_y if actual_y is not None else y_pos
                    data_callback(pos_x, pos_y, x_idx, y_idx)
                
                # Update progress
                processed_points += 1
                self.scan_progress['completed_points'] = processed_points
                self.scan_progress['points_done'].append((y_idx, x_idx))
                self.scan_progress['current_position'] = (y_idx, x_idx)
                
                if show_progress:
                    elapsed = time.time() - start_time
                    points_per_second = processed_points / elapsed if elapsed > 0 else 0
                    remaining = (total_points - processed_points) / points_per_second if points_per_second > 0 else 0
                    
                    print(f"\rProgress: {processed_points}/{total_points} points " +
                        f"({processed_points/total_points*100:.1f}%) - " +
                        f"ETA: {int(remaining/60)}m {int(remaining%60)}s", end="")
            
            if show_progress:
                print()  # New line after progress display
            
            logger.info(f"Scan completed successfully ({processed_points}/{total_points} points)")
            
            # IMPROVED: Clean shutdown sequence
            self._safe_shutdown_after_scan()
            return True
            
        except Exception as e:
            logger.error(f"Error during scan: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            
            # Try to ensure motors are off in case of exception
            self._safe_shutdown_after_scan()
            return False

        # try:
        #     # OPTIMIZATION: Do one-time setup at the beginning
        #     # Ensure we're in serial mode
        #     self.motor_controller.set_mode(OperationMode.MODE_SERIAL)
            
        #     # Enable motors just once at the beginning
        #     self.motor_controller.enable_motors()
            
        #     # Short pause to let motors initialize
        #     time.sleep(0.5)
            
        #     # Loop through all positions in the grid
        #     for y_idx in range(y_steps):
        #         y_pos = int(y_range[0] + (y_range[1] - y_range[0]) * y_idx / max(1, y_steps - 1))
                
        #         # Determine x range for this row (snake pattern)
        #         if y_idx % 2 == 0:  # Even rows: left to right
        #             x_indices = range(x_steps)
        #         else:  # Odd rows: right to left
        #             x_indices = range(x_steps-1, -1, -1)
                
        #         for x_idx_in_row in x_indices:
        #             # Convert the x_idx_in_row to the actual x_idx for data storage
        #             x_idx = x_idx_in_row if y_idx % 2 == 0 else (x_steps - 1 - x_idx_in_row)
                    
        #             # Skip if we've already processed this point (for resume)
        #             point_key = (y_idx, x_idx)
        #             if point_key in points_done:
        #                 logger.info(f"Skipping already processed point at y={y_idx}, x={x_idx}")
        #                 continue
                    
        #             # Calculate position
        #             x_pos = int(x_range[0] + (x_range[1] - x_range[0]) * x_idx / max(1, x_steps - 1))
                    
        #             if show_progress:
        #                 logger.info(f"Moving to position ({x_pos}, {y_pos})")
                    
        #             # Move to position with improved error handling
        #             move_success = self.move_to_position(x_pos, y_pos)
                    
        #             if not move_success:
        #                 logger.error(f"Failed to move to position ({x_pos}, {y_pos})")
        #                 self.motor_controller.disable_motors()  # Ensure motors are off on failure
        #                 # Save progress for potential resume
        #                 self.scan_progress['current_position'] = (y_idx, x_idx)
        #                 return False
                    
        #             # Get the actual position reached
        #             actual_x, actual_y = self.motor_controller.get_position()
        #             if actual_x is not None and actual_y is not None:
        #                 logger.info(f"Position reached: X={actual_x}, Y={actual_y}")
                    
        #             # Additional delay for stability if provided
        #             if delay > 0:
        #                 time.sleep(delay)
                    
        #             # This is where data acquisition would happen
        #             if data_callback:
        #                 logger.info(f"Acquiring data at position ({x_pos}, {y_pos})")
        #                 # Pass the actual position if available, otherwise target position
        #                 pos_x = actual_x if actual_x is not None else x_pos
        #                 pos_y = actual_y if actual_y is not None else y_pos
        #                 data_callback(pos_x, pos_y, x_idx, y_idx)
                    
        #             # Update progress
        #             processed_points += 1
        #             self.scan_progress['completed_points'] = processed_points
        #             self.scan_progress['points_done'].append(point_key)
        #             self.scan_progress['current_position'] = (y_idx, x_idx)
                    
        #             if show_progress:
        #                 elapsed = time.time() - start_time
        #                 points_per_second = processed_points / elapsed if elapsed > 0 else 0
        #                 remaining = (total_points - processed_points) / points_per_second if points_per_second > 0 else 0
                        
        #                 print(f"\rProgress: {processed_points}/{total_points} points " +
        #                       f"({processed_points/total_points*100:.1f}%) - " +
        #                       f"ETA: {int(remaining/60)}m {int(remaining%60)}s", end="")
            
        #     if show_progress:
        #         print()  # New line after progress display
                
        #     # Verify we completed all points
        #     if processed_points < total_points:
        #         logger.warning(f"Scan incomplete: {processed_points}/{total_points} points")
        #         return False
                
        #     logger.info(f"Scan completed successfully ({processed_points}/{total_points} points)")
            
        #     # Switch back to joystick mode and disable motors
        #     self.motor_controller.set_mode(OperationMode.MODE_JOYSTICK)
        #     self.motor_controller.disable_motors()
            
        #     return True
            
        # except Exception as e:
        #     logger.error(f"Error during scan: {e}")
        #     import traceback
        #     logger.debug(traceback.format_exc())
            
        #     # Try to ensure motors are off in case of exception
        #     try:
        #         self.motor_controller.disable_motors()
        #     except:
        #         pass
        #     return False
            
        # finally:
        #     # This safer shutdown sequence ensures proper cleanup
        #     try:
        #         # Stop any movement first
        #         self.motor_controller.stop()
        #         time.sleep(0.5)
                
        #         # Disable motors before mode change
        #         self.motor_controller.disable_motors()
        #         time.sleep(0.5)
                
        #         # Switch to joystick mode
        #         self.motor_controller.set_mode(OperationMode.MODE_JOYSTICK)
        #     except Exception as e:
        #         logger.warning(f"Error during scan cleanup: {e}")

# Example usage
def run_sample_scan():
    """Run a sample scan without data collection"""
    # Optional data acquisition callback function
    def data_callback(x_pos, y_pos, x_idx, y_idx):
        print(f"Data acquisition at ({x_pos}, {y_pos}) - grid position ({x_idx}, {y_idx})")
        # This is where you would collect real data
        # For example:
        # spectrum = spectrometer.capture()
        # data_cube[y_idx, x_idx, :] = spectrum
    
    scanner = EnhancedScanner('COM6')  # Adjust port as needed
    
    try:
        print("Connecting to hardware...")
        if not scanner.connect():
            print("Failed to connect to hardware")
            return
        
        print("Initializing scan...")
        scanner.initialize_scan(
            x_range=(0, 100),  # X range in steps
            y_range=(0, 100),  # Y range in steps
            x_steps=5,         # 5x5 grid for quick test
            y_steps=5
        )
        
        print("Running scan...")
        scanner.perform_scan(data_callback=data_callback)  # Pass the callback
        
        print("Scan complete")
        
    finally:
        print("Disconnecting...")
        scanner.disconnect()
        print("Disconnected")

if __name__ == "__main__":
    run_sample_scan()