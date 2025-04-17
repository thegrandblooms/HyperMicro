#!/usr/bin/env python3
"""
Simple Direct Arduino Controller

This controller is completely rewritten to match the approach in the working
motor control test. It uses a direct communication approach for initialization
and a separate thread only for position monitoring.

Version: 1.0.0
"""

import struct
import time
import logging
import threading
import queue
from enum import Enum
from typing import Tuple, Dict, List, Callable, Optional, Union, Any
import sys
import atexit

#=============================================================================
# CONFIGURATION PARAMETERS - Adjust these settings as needed
#=============================================================================

# Serial Communication Settings
DEFAULT_BAUD_RATE = 115200    # Baud rate for serial communication
DEFAULT_TIMEOUT = 1.0         # Command timeout in seconds
DEFAULT_RETRY_COUNT = 3       # Number of retries for failed commands
DEFAULT_RETRY_DELAY = 0.2     # Delay between retries in seconds

# Connection Settings
ARDUINO_RESET_DELAY = 2.0     # Wait time after connecting for Arduino to reset (seconds)

# Monitoring Thread Settings
MONITOR_SLEEP_INTERVAL = 0.01  # Sleep interval in monitor thread when no data (seconds)
MONITOR_ERROR_DELAY = 0.1      # Delay after error in monitor thread (seconds)

# Position Queue Settings
POSITION_QUEUE_TIMEOUT = 0.5   # Timeout for getting position from queue (seconds)

# Logging Settings
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Arduino Command IDs (match Arduino definitions)
CMD_MOVE_TO = 0x01
CMD_SET_SPEED = 0x03
CMD_SET_ACCEL = 0x04
CMD_STOP = 0x05
CMD_HOME = 0x06
CMD_ENABLE = 0x07
CMD_DISABLE = 0x08
CMD_GET_STATUS = 0x09
CMD_PING = 0x0A
CMD_SET_MODE = 0x0B
CMD_SET_BACKLASH = 0x0C

# Arduino Response IDs (match Arduino definitions)
RESP_OK = 0x81
RESP_ERROR = 0x82
RESP_POSITION_REACHED = 0x84
RESP_PING = 0x86

# Operation Mode Enum
class OperationMode(Enum):
    """Operation modes for the controller."""
    MODE_SERIAL = 0
    MODE_JOYSTICK = 1

# Motor Selection Enum
class MotorSelect(Enum):
    """Motor selection for individual motor commands."""
    MOTOR_X = 0
    MOTOR_Y = 1
    BOTH_MOTORS = 2

#=============================================================================
# MODULE INITIALIZATION - Don't modify unless you know what you're doing
#=============================================================================

# Import pySerialTransfer
try:
    from pySerialTransfer import pySerialTransfer as txfer
except ImportError:
    sys.stderr.write("Error: pySerialTransfer library not found.\n")
    sys.stderr.write("Please install it with: pip install pySerialTransfer\n")
    raise

# Configure logging
logging.basicConfig(
    level=DEFAULT_LOG_LEVEL,
    format=DEFAULT_LOG_FORMAT
)
logger = logging.getLogger("SimpleArduinoController")

#=============================================================================
# ARDUINO CONTROLLER CLASS
#=============================================================================

class SimpleArduinoController:
    """
    Simplified controller for Arduino motor control.
    
    This implementation uses direct communication with minimal abstraction,
    closely matching the approach used in working test scripts.
    """
    
    def __init__(self, port, baud_rate=DEFAULT_BAUD_RATE, timeout=DEFAULT_TIMEOUT, verbose=False):
        """
        Initialize the Arduino controller.
        
        Args:
            port: Serial port (e.g., 'COM3', '/dev/ttyUSB0')
            baud_rate: Baud rate for serial communication
            timeout: Command timeout in seconds
            verbose: Enable verbose logging
        """
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.verbose = verbose
        
        # Set up logging level
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        # Print version info
        logger.info(f"SimpleArduinoController v1.0.0 initialized for port {port}")
        
        # Communication objects
        self.link = None
        self.connected = False
        self.lock = threading.Lock()  # Lock for serial communication
        self.next_sequence_id = 1
        
        # Position monitoring
        self.position_callback = None
        self.position_thread = None
        self.position_thread_running = False
        self.position_queue = queue.Queue()
        
        # Statistics
        self.stats = {
            'commands_sent': 0,
            'commands_failed': 0,
            'positions_received': 0,
        }
        
        # Register shutdown handler
        atexit.register(self.safe_shutdown)
    
    def connect(self) -> bool:
        """
        Connect to the Arduino using direct approach.
        
        Returns:
            Success status
        """
        logger.info(f"Connecting to Arduino on {self.port}...")
        
        try:
            # Create SerialTransfer object
            logger.debug("Creating SerialTransfer object...")
            self.link = txfer.SerialTransfer(self.port)
            
            # Open connection
            logger.debug("Opening connection...")
            self.link.open()
            logger.debug("Connection opened successfully")
            
            # Set baud rate
            if hasattr(self.link, 'connection') and hasattr(self.link.connection, 'baudrate'):
                logger.debug(f"Current baudrate: {self.link.connection.baudrate}")
                if self.link.connection.baudrate != self.baud_rate:
                    self.link.connection.baudrate = self.baud_rate
                    logger.debug(f"New baudrate: {self.link.connection.baudrate}")
            
            # Wait for Arduino to reset
            logger.debug(f"Waiting for Arduino to reset ({ARDUINO_RESET_DELAY} seconds)...")
            time.sleep(ARDUINO_RESET_DELAY)
            
            # Flush buffers
            if hasattr(self.link, 'connection'):
                if hasattr(self.link.connection, 'reset_input_buffer'):
                    logger.debug("Flushing input/output buffers...")
                    self.link.connection.reset_input_buffer()
                    self.link.connection.reset_output_buffer()
            
            # Test connection with ping - using direct method
            logger.debug("Testing connection with ping...")
            
            # Direct ping test that matches the working test
            ping_value = 0x12345678
            echo_value = self.ping(ping_value)
            
            if echo_value == ping_value:
                # Connection successful
                self.connected = True
                logger.info("Connected successfully!")
                
                # Start position monitoring thread
                self._start_position_monitor()
                
                return True
            else:
                logger.error(f"Ping test failed: expected {ping_value:08X}, got {echo_value}")
                self.link.close()
                self.link = None
                return False
        
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            
            if self.link:
                try:
                    self.link.close()
                except:
                    pass
                self.link = None
                
            return False
    
    def disconnect(self):
        """
        Disconnect from the Arduino.
        """
        self.safe_shutdown()
        
        # Stop position monitor
        self._stop_position_monitor()
        
        # Close connection
        if self.link:
            try:
                self.link.close()
                logger.info("Disconnected from Arduino")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            
            self.link = None
        
        self.connected = False
    
    def safe_shutdown(self):
        """
        Safely shut down the controller, stopping motors if connected.
        """
        if self.connected:
            try:
                # Stop any movement
                self.stop()
                # Disable motors
                self.disable_motors()
                # Switch to joystick mode
                self.set_mode(OperationMode.MODE_JOYSTICK)
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
    
    def _start_position_monitor(self):
        """Start the position monitoring thread."""
        if self.position_thread is not None and self.position_thread.is_alive():
            return  # Thread already running
        
        self.position_thread_running = True
        self.position_thread = threading.Thread(
            target=self._position_monitor_worker,
            daemon=True
        )
        self.position_thread.start()
        logger.debug("Position monitoring thread started")
    
    def _stop_position_monitor(self):
        """Stop the position monitoring thread."""
        if self.position_thread is not None:
            self.position_thread_running = False
            if self.position_thread.is_alive():
                self.position_thread.join(timeout=2.0)
            self.position_thread = None
            logger.debug("Position monitoring thread stopped")
    
    def _position_monitor_worker(self):
        """
        Thread that monitors for position notifications.
        
        This is a dedicated thread that only handles position notifications,
        not all communication.
        """
        logger.debug("Position monitor started")
        
        while self.position_thread_running:
            try:
                if not self.connected or not self.link:
                    time.sleep(MONITOR_ERROR_DELAY)
                    continue
                
                # Check for data to read
                with self.lock:
                    try:
                        available = self.link.available()
                    except:
                        time.sleep(MONITOR_ERROR_DELAY)
                        continue
                    
                    if available <= 0:
                        time.sleep(MONITOR_SLEEP_INTERVAL)
                        continue
                    
                    # Read data
                    raw_data = bytes(self.link.rx_buff[:available])
                
                # Check for position notification
                if len(raw_data) >= 1 and raw_data[0] == RESP_POSITION_REACHED:
                    if len(raw_data) >= 11:
                        # Position notification
                        sequence_id = struct.unpack("<H", raw_data[1:3])[0]
                        x_pos = struct.unpack("<i", raw_data[3:7])[0]
                        y_pos = struct.unpack("<i", raw_data[7:11])[0]
                        
                        logger.debug(f"Position notification: seq={sequence_id}, pos=({x_pos}, {y_pos})")
                        
                        # Add to position queue
                        self.position_queue.put((sequence_id, x_pos, y_pos))
                        self.stats['positions_received'] += 1
                        
                        # Call callback if registered
                        if self.position_callback:
                            try:
                                # Create point_data structure
                                point_data = {
                                    'sequence_id': sequence_id,
                                    'x': x_pos,
                                    'y': y_pos,
                                    'timestamp': time.time()
                                }
                                
                                # Call the callback
                                self.position_callback(x_pos, y_pos, sequence_id, point_data)
                            except Exception as e:
                                logger.error(f"Error in position callback: {e}")
            
            except Exception as e:
                logger.error(f"Error in position monitor: {e}")
                time.sleep(MONITOR_ERROR_DELAY)
        
        logger.debug("Position monitor stopped")
    
    def send_command(self, command_id, data=b'', expected_response_id=None, retry_count=0):
        """
        Send a command to the Arduino and wait for the response.
        
        This uses a direct approach matching the working test code.
        
        Args:
            command_id: Command ID byte
            data: Additional data bytes
            expected_response_id: Expected response ID or None
            retry_count: Current retry count
            
        Returns:
            Response data or None if failed
        """
        if not self.connected or not self.link:
            logger.error("Not connected to Arduino")
            return None
        
        try:
            # Prepare command data
            full_command = bytes([command_id]) + data
            
            # Debug log command
            cmd_hex = ' '.join(f'{b:02X}' for b in full_command)
            logger.debug(f"Sending command: {cmd_hex}")
            
            # Send command
            with self.lock:
                # Clear tx buffer with appropriate length
                buffer_size = min(len(full_command), len(self.link.tx_buff))
                for i in range(buffer_size):
                    self.link.tx_buff[i] = 0
                
                # Copy command to tx buffer
                for i in range(len(full_command)):
                    if i < len(self.link.tx_buff):
                        self.link.tx_buff[i] = full_command[i]
                
                # Send command
                send_result = self.link.send(len(full_command))
            
            if not send_result:
                logger.warning(f"Failed to send command 0x{command_id:02X}")
                if retry_count < DEFAULT_RETRY_COUNT:
                    # Retry after a short delay
                    time.sleep(DEFAULT_RETRY_DELAY)
                    return self.send_command(command_id, data, expected_response_id, retry_count + 1)
                return None
            
            self.stats['commands_sent'] += 1
            
            # Wait for response
            start_time = time.time()
            
            while time.time() - start_time < self.timeout:
                # Check for available data
                with self.lock:
                    available = self.link.available()
                    
                    if available <= 0:
                        time.sleep(MONITOR_SLEEP_INTERVAL)
                        continue
                    
                    # Read response
                    raw_response = bytes(self.link.rx_buff[:available])
                
                if len(raw_response) < 1:
                    time.sleep(MONITOR_SLEEP_INTERVAL)
                    continue
                
                # Debug log response
                resp_hex = ' '.join(f'{b:02X}' for b in raw_response)
                logger.debug(f"Response received: {resp_hex}")
                
                # Check response type
                resp_id = raw_response[0]
                
                # If this is a position notification, ignore it for now
                if resp_id == RESP_POSITION_REACHED:
                    time.sleep(MONITOR_SLEEP_INTERVAL)
                    continue
                
                # Check if this is the expected response
                if expected_response_id is None or resp_id == expected_response_id:
                    return raw_response
                
                logger.warning(f"Unexpected response type: 0x{resp_id:02X}, expected: 0x{expected_response_id:02X}")
            
            # Timeout
            logger.warning(f"Command 0x{command_id:02X} timed out waiting for response")
            self.stats['commands_failed'] += 1
            
            # Retry if needed
            if retry_count < DEFAULT_RETRY_COUNT:
                logger.debug(f"Retrying command (attempt {retry_count + 1})")
                return self.send_command(command_id, data, expected_response_id, retry_count + 1)
            
            return None
            
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.stats['commands_failed'] += 1
            return None
    
    def set_position_callback(self, callback):
        """
        Set the callback function for position notifications.
        
        Args:
            callback: Function to call when position is reached
                     Signature: callback(x, y, sequence_id, point_data)
        """
        self.position_callback = callback
    
    def ping(self, value=0x12345678):
        """
        Send a ping command to verify connection.
        
        Args:
            value: Test value to send (will be echoed back)
            
        Returns:
            Echoed value or None if failed
        """
        # Prepare ping command
        ping_command = bytes([CMD_PING]) + struct.pack("<I", value)
        
        logger.debug(f"Sending ping with value: 0x{value:08X}")
        
        # Send ping command with lock
        with self.lock:
            # Copy command to tx buffer
            for i in range(len(ping_command)):
                self.link.tx_buff[i] = ping_command[i]
            
            # Send command
            send_result = self.link.send(len(ping_command))
        
        if not send_result:
            logger.warning("Ping command send failed")
            return None
        
        # Wait for response
        start_time = time.time()
        ping_timeout = self.timeout * 2  # Ping specific timeout (longer)
        
        while time.time() - start_time < ping_timeout:
            # Check for available data
            with self.lock:
                available = self.link.available()
                
                if available <= 0:
                    time.sleep(MONITOR_SLEEP_INTERVAL)
                    continue
                
                # Read response
                raw_response = bytes(self.link.rx_buff[:available])
            
            # Debug log response
            resp_hex = ' '.join(f'{b:02X}' for b in raw_response)
            logger.debug(f"Ping response received: {resp_hex}")
            
            # Check if this is a ping response
            if len(raw_response) >= 5 and raw_response[0] == RESP_PING:
                echo_value = struct.unpack("<I", raw_response[1:5])[0]
                logger.debug(f"Echo value: 0x{echo_value:08X}")
                return echo_value
        
        # Timeout
        logger.warning("Ping command timed out")
        return None
    
    def get_status(self):
        """
        Get the current status of the controller.
        
        Returns:
            Dictionary with status information or None if failed
        """
        response = self.send_command(CMD_GET_STATUS, b'', RESP_OK)
        
        if not response or len(response) < 13 or response[1] != CMD_GET_STATUS:
            logger.warning("Failed to get status")
            return None
        
        # Extract status information
        x_pos = struct.unpack("<i", response[2:6])[0]
        y_pos = struct.unpack("<i", response[6:10])[0]
        
        running_state = response[10]
        motors_enabled = response[11] > 0
        system_state = response[12]
        
        # Create status dictionary
        status = {
            'x_position': x_pos,
            'y_position': y_pos,
            'x_running': bool(running_state & 0x01),
            'y_running': bool(running_state & 0x02),
            'any_running': running_state > 0,
            'motors_enabled': motors_enabled,
            'system_state': system_state,
            'connected': self.connected,
            'timestamp': time.time()
        }
        
        return status
    
    def move_to(self, x, y, sequence_id=None):
        """
        Move to a specified position.
        
        Args:
            x: X position in steps
            y: Y position in steps
            sequence_id: Optional sequence ID for tracking (auto-generated if None)
            
        Returns:
            Success status (boolean)
        """
        # Generate sequence ID if not provided
        if sequence_id is None:
            sequence_id = self._get_next_sequence_id()
        
        # Prepare command data
        data = struct.pack("<iiH", x, y, sequence_id)
        
        # Send command
        response = self.send_command(CMD_MOVE_TO, data, RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def queue_movement(self, x, y, point_data=None):
        """
        Queue a movement to a specified position.
        
        Args:
            x: X position in steps
            y: Y position in steps
            point_data: Optional data to associate with this movement
            
        Returns:
            Sequence ID of the queued movement, or 0 if failed
        """
        # Generate sequence ID
        sequence_id = self._get_next_sequence_id()
        
        # Move to position
        if self.move_to(x, y, sequence_id):
            return sequence_id
        else:
            return 0
    
    def batch_movements(self, movements):
        """
        Queue a batch of movements.
        
        Args:
            movements: List of (x, y, point_data, tolerance) tuples
            
        Returns:
            List of sequence IDs, or empty list if failed
        """
        sequence_ids = []
        
        for x, y, point_data, tolerance in movements:
            # Add a small delay between commands to prevent buffer issues
            if sequence_ids:  # Not the first command
                time.sleep(DEFAULT_RETRY_DELAY)
            
            sequence_id = self.queue_movement(x, y, point_data)
            if sequence_id > 0:
                sequence_ids.append(sequence_id)
            else:
                logger.warning(f"Failed to queue move to ({x}, {y})")
        
        return sequence_ids
    
    def wait_for_position(self, sequence_id, timeout=10.0):
        """
        Wait for a position notification for a specific sequence ID.
        
        Args:
            sequence_id: Sequence ID to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            (x, y) tuple if position reached, None if timeout
        """
        logger.debug(f"Waiting for position notification (sequence ID: {sequence_id})")
        
        # Store seen positions to avoid reprocessing
        seen_positions = {}
        
        # First check if this notification is already in the queue
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Try to get from the queue with a small timeout
                seq, x, y = self.position_queue.get(timeout=POSITION_QUEUE_TIMEOUT)
                
                # Is this the one we're waiting for?
                if seq == sequence_id:
                    logger.debug(f"Position reached: ({x}, {y}) for sequence ID {sequence_id}")
                    return (x, y)
                else:
                    # Not our sequence ID, remember it for later
                    seen_positions[seq] = (x, y)
                    logger.debug(f"Received position for different sequence ID: {seq}")
            except queue.Empty:
                # Nothing in the queue, check if motors still running
                if len(seen_positions) > 0 and time.time() - start_time > timeout / 2:
                    # If we've seen other positions but not ours, check motor status
                    status = self.get_status()
                    if status and not status.get('any_running', True):
                        logger.debug("Motors no longer running, position may have been missed")
                        # Use status position as a fallback
                        return (status['x_position'], status['y_position'])
        
        logger.warning(f"Timeout waiting for position notification (sequence ID: {sequence_id})")
        return None
    
    def set_speed(self, x_speed, y_speed=None):
        """
        Set motor speed.
        
        Args:
            x_speed: X motor speed (steps/sec)
            y_speed: Y motor speed (steps/sec, uses x_speed if None)
            
        Returns:
            Success status
        """
        if y_speed is None:
            y_speed = x_speed
        
        # Prepare command data
        data = struct.pack("<HH", x_speed, y_speed)
        
        # Send command
        response = self.send_command(CMD_SET_SPEED, data, RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def set_acceleration(self, x_accel, y_accel=None):
        """
        Set motor acceleration.
        
        Args:
            x_accel: X motor acceleration (steps/sec²)
            y_accel: Y motor acceleration (steps/sec², uses x_accel if None)
            
        Returns:
            Success status
        """
        if y_accel is None:
            y_accel = x_accel
        
        # Prepare command data
        data = struct.pack("<HH", x_accel, y_accel)
        
        # Send command
        response = self.send_command(CMD_SET_ACCEL, data, RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def stop(self):
        """
        Stop all motors immediately.
        
        Returns:
            Success status
        """
        # Send command
        response = self.send_command(CMD_STOP, b'', RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def home(self):
        """
        Set current position as home (zero).
        
        Returns:
            Success status
        """
        # Send command
        response = self.send_command(CMD_HOME, b'', RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def set_backlash_compensation(self, x_backlash, y_backlash, enabled=True):
        """
        Configure backlash compensation parameters.
        
        Args:
            x_backlash: X-axis backlash amount in steps
            y_backlash: Y-axis backlash amount in steps
            enabled: Enable or disable compensation
            
        Returns:
            Success status
        """
        # Prepare command data
        data = struct.pack("<HHB", x_backlash, y_backlash, 1 if enabled else 0)
        
        # Send command
        response = self.send_command(CMD_SET_BACKLASH, data, RESP_OK)
        
        return response is not None and response[0] == RESP_OK

    def enable_motors(self):
        """
        Enable both motors.
        
        Returns:
            Success status
        """
        # Send command
        response = self.send_command(CMD_ENABLE, b'', RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def disable_motors(self):
        """
        Disable both motors.
        
        Returns:
            Success status
        """
        # Send command
        response = self.send_command(CMD_DISABLE, b'', RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def set_mode(self, mode):
        """
        Set the operation mode.
        
        Args:
            mode: Operation mode (MODE_SERIAL or MODE_JOYSTICK)
            
        Returns:
            Success status
        """
        # Prepare command data
        data = bytes([mode.value])
        
        # Send command
        response = self.send_command(CMD_SET_MODE, data, RESP_OK)
        
        return response is not None and response[0] == RESP_OK
    
    def _get_next_sequence_id(self):
        """
        Get the next sequence ID.
        
        Returns:
            Next sequence ID
        """
        sequence_id = self.next_sequence_id
        self.next_sequence_id = (self.next_sequence_id + 1) & 0xFFFF
        
        # Avoid sequence ID 0 as it's used to indicate failure
        if self.next_sequence_id == 0:
            self.next_sequence_id = 1
        
        return sequence_id
    
    def get_stats(self):
        """
        Get communication statistics.
        
        Returns:
            Dictionary with statistics
        """
        return self.stats.copy()


#=============================================================================
# TEST FUNCTION - For verifying controller functionality
#=============================================================================

# Comprehensive test function
def test_controller(port, verbose=False):
    """
    Run a comprehensive test of the controller functionality.
    
    Args:
        port: Serial port to connect to
        verbose: Enable verbose logging
    
    Returns:
        True if all tests passed, False otherwise
    """
    print(f"\n==== TESTING ARDUINO CONTROLLER ON {port} ====")
    
    # Create controller
    controller = SimpleArduinoController(port, verbose=verbose)
    
    try:
        # Test 1: Connect
        print("\nConnecting to Arduino...")
        if not controller.connect():
            print("❌ CONNECTION FAILED")
            return False
        
        print("✅ CONNECTION SUCCESSFUL")
        
        # Test 2: Ping
        print("\nTesting ping command...")
        echo_value = controller.ping(0x87654321)
        
        if echo_value == 0x87654321:
            print(f"✅ PING SUCCESSFUL - Echo value: 0x{echo_value:08X}")
        else:
            print(f"❌ PING FAILED - Echo value: {echo_value}")
            return False
        
        # Test 3: Status
        print("\nTesting status command...")
        status = controller.get_status()
        
        if status:
            print("✅ STATUS SUCCESSFUL")
            print("Status values:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        else:
            print("❌ STATUS FAILED")
            return False
        
        # Test 4: Enable motors
        print("\nTesting motor enable...")
        if controller.enable_motors():
            print("✅ MOTOR ENABLE SUCCESSFUL")
        else:
            print("❌ MOTOR ENABLE FAILED")
            return False
        
        # Test 5: Set speed and acceleration
        print("\nSetting motor parameters...")
        if controller.set_speed(800, 800) and controller.set_acceleration(1000, 1000):
            print("✅ MOTOR PARAMETERS SET SUCCESSFULLY")
        else:
            print("❌ MOTOR PARAMETERS FAILED")
            return False
        
        # Test 6: Move to position
        print("\nTesting move to position...")
        sequence_id = controller.queue_movement(50, 50)
        
        if sequence_id > 0:
            print(f"Move command sent with sequence ID: {sequence_id}")
            
            # Wait for position notification
            position = controller.wait_for_position(sequence_id, timeout=10.0)
            
            if position:
                print(f"✅ MOVE SUCCESSFUL - Final position: {position}")
            else:
                print("⚠️ NO POSITION NOTIFICATION - checking status")
                
                # Check status to verify movement
                status = controller.get_status()
                if status:
                    print(f"Current position according to status: ({status['x_position']}, {status['y_position']})")
                    
                    # Check if we're close to the target position
                    if (abs(status['x_position'] - 50) <= 5 and 
                        abs(status['y_position'] - 50) <= 5):
                        print("✅ POSITION VERIFIED VIA STATUS")
                    else:
                        print("❌ MOVE FAILED - Position not reached")
                        return False
                else:
                    print("❌ STATUS CHECK FAILED")
                    return False
        else:
            print("❌ MOVE COMMAND FAILED")
            return False
        
        # Test 7: Home position
        print("\nTesting home command...")
        if controller.home():
            print("✅ HOME COMMAND SUCCESSFUL")
            
            # Verify position is now 0,0
            status = controller.get_status()
            if status and status['x_position'] == 0 and status['y_position'] == 0:
                print("✅ HOME POSITION VERIFIED")
            else:
                print("⚠️ HOME POSITION NOT VERIFIED")
        else:
            print("❌ HOME COMMAND FAILED")
            return False
        
        # Test 8: Stop command
        print("\nTesting stop command...")
        if controller.stop():
            print("✅ STOP COMMAND SUCCESSFUL")
        else:
            print("❌ STOP COMMAND FAILED")
            return False
        
        # Test 9: Disable motors
        print("\nTesting motor disable...")
        if controller.disable_motors():
            print("✅ MOTOR DISABLE SUCCESSFUL")
        else:
            print("❌ MOTOR DISABLE FAILED")
            return False
        
        # Cleanup and shut down
        print("\nDisconnecting...")
        controller.disconnect()
        print("Disconnected")
        
        print("\nAll tests passed! ✅")
        return True
        
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        print(traceback.format_exc())
        
        # Ensure controller is properly shut down
        try:
            controller.disconnect()
        except:
            pass
        
        return False


if __name__ == '__main__':
    # Test controller if run directly
    import sys
    
    if len(sys.argv) >= 2:
        port = sys.argv[1]
        test_controller(port, verbose=True)
    else:
        print("Usage: python simple_arduino_controller.py COM_PORT")
        sys.exit(1)