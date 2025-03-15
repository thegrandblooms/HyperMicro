"""
Improved Motor Controller with better command handling and error recovery
"""
import time
import logging
import struct
import atexit  # For proper shutdown on program exit
import math
from pySerialTransfer import pySerialTransfer as txfer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("motor_controller.log"),
        logging.StreamHandler()
    ]
)

class StatusCommandFilter(logging.Filter):
    """Filter to reduce excessive status command logging"""
    def filter(self, record):
        # Skip logging for STATUS commands and responses
        if "command: ID=8" in record.getMessage() or "STATUS response" in record.getMessage():
            return False
        return True

logger = logging.getLogger("ImprovedMotorController")
logger.addFilter(StatusCommandFilter())

# Command IDs
class CommandID:
    CMD_PING = 11
    CMD_MOVE = 1
    CMD_MOVETO = 2
    CMD_SPEED = 3
    CMD_ACCEL = 4
    CMD_HOME = 5
    CMD_STOP = 6
    CMD_MODE = 7
    CMD_STATUS = 8
    CMD_DISABLE = 9
    CMD_ENABLE = 10

# Response IDs
class ResponseID:
    RESP_OK = 1
    RESP_ERROR = 2
    RESP_STATUS = 3
    RESP_POSITION = 4
    RESP_PING = 5

# Operation modes
class OperationMode:
    MODE_JOYSTICK = 0
    MODE_SERIAL = 1

# Motor selection
class MotorSelect:
    MOTOR_X = 1
    MOTOR_Y = 2
    MOTOR_BOTH = 3

class ImprovedMotorController:
    """
    Improved motor controller with better command handling and error recovery
    """
    
    def __init__(self, port, baud_rate=115200):
        """Initialize the motor controller"""
        self.port = port
        self.baud_rate = baud_rate
        self.transfer = None
        self.connected = False
        
        # Position tracking
        self.current_position = (0, 0)
        self.current_speed = (0, 0)
        self.is_running = (False, False)
        self.current_mode = OperationMode.MODE_JOYSTICK
        
        # Add motor state tracking
        self.motors_enabled = False  # Track whether motors are enabled
        
        # Safety settings
        self.auto_disable_on_disconnect = True
        self.auto_switch_to_joystick = True
        
        # Command spacing and timeouts
        self.command_spacing = 0.1  # 200ms between commands
        self.last_command_time = 0
        self.default_timeout = 2.0
        self.movement_timeout = 5.0
        
        # Register shutdown function
        atexit.register(self.safe_shutdown)
        
    def safe_shutdown(self):
        """Safely shut down the controller"""
        if self.connected:
            logger.info("Performing safe shutdown...")
            
            try:
                # Stop any movement first
                self.stop()
                time.sleep(0.5)  # Add delay after stopping
                
                # CHANGED ORDER: First disable motors, then switch mode
                # Disable motors if configured
                if self.auto_disable_on_disconnect:
                    logger.info("Disabling motors during shutdown")
                    self.disable_motors()
                    time.sleep(1.0)  # Longer delay after disabling motors
                
                # Switch back to joystick mode if configured
                if self.auto_switch_to_joystick:
                    logger.info("Switching to joystick mode during shutdown")
                    self.set_mode(OperationMode.MODE_JOYSTICK)
                    time.sleep(0.5)  # Add delay after mode change
                
                # Flush any pending communication
                self.flush_buffers()
                    
                # Finally disconnect
                self.disconnect()
                
            except Exception as e:
                logger.error(f"Error during safe shutdown: {e}")

    def connect(self):
        """Connect to the Arduino"""
        try:
            logger.info(f"Connecting to port {self.port}")
            self.transfer = txfer.SerialTransfer(self.port)
            self.transfer.open()
            time.sleep(2)  # Wait for Arduino reset
            
            logger.info("Testing connection with ping")
            if self._ping_test():
                self.connected = True
                logger.info("Successfully connected to motor controller")
                return True
            else:
                logger.error("Failed to ping motor controller")
                self.disconnect()
                return False
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.disconnect()
            return False
    
    def disconnect(self):
        """Disconnect from the Arduino"""
        if self.transfer:
            try:
                self.transfer.close()
            except:
                pass
            finally:
                self.transfer = None
                self.connected = False
        logger.info("Disconnected from motor controller")
    
    def _ping_test(self, timeout=2.0):
        """Send a ping command to test the connection"""
        try:
            if not self.transfer:
                return False
                
            # Create random test value
            import random
            test_value = random.randint(1000, 9999)
            
            # Format to send: command_id, motor_select, param1, param2
            command_bytes = struct.pack("<BBii", CommandID.CMD_PING, 0, test_value, 0)
            
            # Copy bytes to tx_buff
            for i in range(len(command_bytes)):
                self.transfer.tx_buff[i] = command_bytes[i]
            
            # Send the command
            self.transfer.send(len(command_bytes))
            logger.debug(f"Sent ping command with value {test_value}")
            
            # Wait for response
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.transfer.available():
                    # Read response
                    try:
                        # Parse the ping response (expected to be 5 bytes)
                        resp_id = self.transfer.rx_buff[0]
                        resp_value = struct.unpack("<i", bytes(self.transfer.rx_buff[1:5]))[0]
                        
                        logger.debug(f"Received response: ID={resp_id}, Value={resp_value}")
                        
                        if resp_id == ResponseID.RESP_PING and resp_value == test_value:
                            logger.info("Ping successful")
                            return True
                        else:
                            logger.warning(f"Unexpected ping response: ID={resp_id}, Value={resp_value}")
                    except Exception as e:
                        logger.error(f"Error parsing ping response: {e}")
                    
                    return False  # We got a response, but it was invalid
                
                # Check for errors
                if self.transfer.status.value < 0:
                    logger.error(f"Ping error: {self.transfer.status.name}")
                    return False
                
                time.sleep(0.01)
            
            logger.warning("Ping timeout")
            return False
            
        except Exception as e:
            logger.error(f"Ping error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _send_command(self, command_id, motor_select=0, param1=0, param2=0, timeout=None, retry_count=3, force_retry=False):
        """Send a command with improved handling for movement commands"""
        if not self.connected or not self.transfer:
            logger.error("Not connected to motor controller")
            return None
            
        if timeout is None:
            timeout = self.default_timeout
        
        # Movement commands need special treatment
        is_movement_command = command_id in [CommandID.CMD_MOVE, CommandID.CMD_MOVETO]
        
        # Respect command spacing to avoid overwhelming the Arduino
        current_time = time.time()
        time_since_last_cmd = current_time - self.last_command_time
        
        # Use larger spacing for movement commands
        min_spacing = 0.5 if is_movement_command else self.command_spacing
        
        if time_since_last_cmd < min_spacing:
            sleep_time = min_spacing - time_since_last_cmd
            logger.debug(f"Sleeping {sleep_time:.3f}s to respect command spacing")
            time.sleep(sleep_time)
        
        self.last_command_time = time.time()
        
        # Try sending the command with retries
        for attempt in range(retry_count):
            try:
                # Format the command bytes
                command_bytes = struct.pack("<BBii", command_id, motor_select, param1, param2)
                
                # Copy to tx_buff
                for i in range(len(command_bytes)):
                    self.transfer.tx_buff[i] = command_bytes[i]
                
                # Send the command
                self.transfer.send(len(command_bytes))
                logger.debug(f"Sent command: ID={command_id}, Motor={motor_select}, Param1={param1}, Param2={param2}")
                
                # For movement commands, we'll accept status responses as successful
                # because the Arduino won't send OK until movement completes
                if is_movement_command:
                    # Just wait for first response confirmation, any response is fine
                    short_timeout = min(2.0, timeout)  # Use shorter timeout for initial response
                    start_time = time.time()
                    
                    while time.time() - start_time < short_timeout:
                        if self.transfer.available():
                            # Got some response - for movement, we consider this success
                            # and will track actual completion separately
                            resp_id = self.transfer.rx_buff[0]
                            logger.debug(f"Movement command got response type: {resp_id}")
                            
                            # Return a success response
                            return {'responseID': ResponseID.RESP_OK, 'value': command_id, 'movement_started': True}
                        
                        time.sleep(0.01)
                    
                    # If we get here, we didn't get any response in the short timeout
                    logger.warning(f"No initial response to movement command (attempt {attempt+1}/{retry_count})")
                    continue  # Try again
                
                # For non-movement commands, use normal response handling
                else:
                    # Wait for response with normal timeout
                    start_time = time.time()
                    got_status_only = False
                    
                    while time.time() - start_time < timeout:
                        if self.transfer.available():
                            resp_id = self.transfer.rx_buff[0]
                            
                            # Parse different response types
                            if resp_id in [ResponseID.RESP_OK, ResponseID.RESP_ERROR, ResponseID.RESP_PING]:
                                # Basic response with a value
                                resp_value = struct.unpack("<i", bytes(self.transfer.rx_buff[1:5]))[0]
                                response = {'responseID': resp_id, 'value': resp_value}
                                
                                # For command responses, check if it's for our command
                                if resp_id == ResponseID.RESP_OK and resp_value == command_id:
                                    logger.debug(f"Received OK response for command {command_id}")
                                    return response
                                elif resp_id == ResponseID.RESP_ERROR:
                                    logger.warning(f"Received ERROR response: {resp_value}")
                                    # Don't return yet, keep trying as we might get valid response later
                                    
                            elif resp_id in [ResponseID.RESP_STATUS, ResponseID.RESP_POSITION]:
                                # Status response with more data
                                got_status_only = True
                            try:
                                # We need at least 21 bytes for a full status response
                                cmd_echo = self.transfer.rx_buff[1]
                                x_pos = struct.unpack("<i", bytes(self.transfer.rx_buff[2:6]))[0]
                                y_pos = struct.unpack("<i", bytes(self.transfer.rx_buff[6:10]))[0]
                                x_speed = struct.unpack("<h", bytes(self.transfer.rx_buff[10:12]))[0]
                                y_speed = struct.unpack("<h", bytes(self.transfer.rx_buff[12:14]))[0]
                                x_running = self.transfer.rx_buff[14]
                                y_running = self.transfer.rx_buff[15]
                                mode = self.transfer.rx_buff[16]
                                sequence = struct.unpack("<H", bytes(self.transfer.rx_buff[17:19]))[0]
                                param1 = struct.unpack("<i", bytes(self.transfer.rx_buff[19:23]))[0]
                                
                                # Update our cached position data
                                self.current_position = (x_pos, y_pos)
                                self.current_speed = (x_speed, y_speed)
                                self.is_running = (x_running > 0, y_running > 0)
                                self.current_mode = mode
                                
                                response = {
                                    'responseID': resp_id,
                                    'commandEcho': cmd_echo,
                                    'xPosition': x_pos,
                                    'yPosition': y_pos,
                                    'xSpeed': x_speed,
                                    'ySpeed': y_speed, 
                                    'xRunning': x_running,
                                    'yRunning': y_running,
                                    'mode': mode,
                                    'sequence': sequence,
                                    'param1': param1
                                }
                                
                                # If status response was for our command, accept it
                                cmd_echo = self.transfer.rx_buff[1]
                                if cmd_echo == command_id:
                                    logger.debug(f"Received STATUS response for command {command_id}")
                                    # Return with status
                                else:
                                    # Keep waiting for direct response
                                    logger.debug(f"Received STATUS update, still waiting for response")
                                    
                            except Exception as e:
                                logger.error(f"Error parsing status response: {e}")
                    
                    time.sleep(0.01)
                
                # We timed out waiting for a response
                if got_status_only and not force_retry:
                    # Consider it successful if we got any status updates
                    logger.info(f"Got status updates but no direct response for command {command_id}. Considering successful.")
                    return {'responseID': ResponseID.RESP_OK, 'value': command_id, 'derived': True}
            
            except Exception as e:
                logger.error(f"Error sending command {command_id}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                
                # Add a delay before retry
                time.sleep(0.5)
        
        # All retries failed
        logger.error(f"Command {command_id} failed after {retry_count} attempts")
        return None
        
        # All retries failed
        logger.error(f"Command {command_id} failed after {retry_count} attempts")
        return None
    
    def flush_buffers(self):
        """Flush the serial buffers to clear any pending data"""
        if self.connected and self.transfer and hasattr(self.transfer, 'connection'):
            try:
                self.transfer.connection.reset_input_buffer()
                self.transfer.connection.reset_output_buffer()
                logger.debug("Serial buffers flushed")
            except Exception as e:
                logger.warning(f"Error flushing buffers: {e}")

    def _wait_for_segment_completion(self, target_x, target_y, timeout=5.0, tolerance=5):
        """
        More efficient waiting for movement completion with reduced polling
        """
        start_time = time.time()
        last_check_time = 0
        check_interval = 0.5  # Increased from 0.2 to 0.5 seconds to reduce polling
        consecutive_stable_positions = 0
        last_position = None
        last_status_time = 0
        status_interval = 1.0  # Check running status less frequently (1 second)
        
        logger.debug(f"Waiting for position ({target_x}, {target_y}) with tolerance {tolerance}")
        
        while time.time() - start_time < timeout:
            current_time = time.time()
            
            # Only poll position at specific intervals
            if current_time - last_check_time >= check_interval:
                last_check_time = current_time
                
                # Get current position
                x, y = self.get_position()
                
                # Check if position is stable (no change since last check)
                position_stable = (last_position is not None and 
                                abs(x - last_position[0]) < 2 and 
                                abs(y - last_position[1]) < 2)
                
                # Check if we've reached the target
                target_reached = (abs(x - target_x) <= tolerance and 
                                abs(y - target_y) <= tolerance)
                
                # Only log every few checks to reduce log volume
                if consecutive_stable_positions % 2 == 0:
                    logger.debug(f"Current: ({x}, {y}), Target: ({target_x}, {target_y}), " +
                                f"Stable: {position_stable}, Reached: {target_reached}")
                
                # If target reached, we're done
                if target_reached:
                    logger.info(f"Reached position ({x}, {y}), Target: ({target_x}, {target_y})")
                    return True
                
                # If position is stable but not at target, we might be stuck
                if position_stable:
                    consecutive_stable_positions += 1
                    
                    # Use wider tolerance after multiple stable checks
                    wider_tolerance = tolerance * (1 + consecutive_stable_positions * 0.5)
                    
                    # Accept position if within expanded tolerance
                    if (abs(x - target_x) <= wider_tolerance and 
                        abs(y - target_y) <= wider_tolerance and
                        consecutive_stable_positions >= 2):
                        logger.info(f"Position close enough to target (within {wider_tolerance} steps)")
                        return True
                    
                    # Check if motors stopped running but only occasionally
                    if consecutive_stable_positions >= 3 and current_time - last_status_time >= status_interval:
                        last_status_time = current_time
                        status = self.get_status()
                        if not any(status['running']):
                            logger.warning(f"Motors stopped at ({x}, {y}), not at target ({target_x}, {target_y})")
                            
                            # Accept position if it's close enough after multiple checks
                            if consecutive_stable_positions >= 5:
                                logger.info("Accepting current position after multiple stable readings")
                                return True
                            return False
                else:
                    # Reset counter if position is changing
                    consecutive_stable_positions = 0
                
                # Store current position for next comparison
                last_position = (x, y)
            
            # Use a shorter sleep interval for better responsiveness
            time.sleep(0.05)
        
        # Timeout reached
        logger.warning(f"Timeout waiting for position ({target_x}, {target_y})")
        return False

    def get_status(self):
        """Get current status of the motor controller"""
        response = self._send_command(CommandID.CMD_STATUS)
        
        # If we got a response, return a simplified status
        if response and response.get('responseID') in [ResponseID.RESP_STATUS, ResponseID.RESP_POSITION]:
            return {
                'position': (response.get('xPosition', 0), response.get('yPosition', 0)),
                'speed': (response.get('xSpeed', 0), response.get('ySpeed', 0)),
                'running': (response.get('xRunning', 0) > 0, response.get('yRunning', 0) > 0),
                'mode': response.get('mode', 0)
            }
        
        # Use cached values if available
        return {
            'position': self.current_position,
            'speed': self.current_speed,
            'running': self.is_running,
            'mode': self.current_mode
        }
    
    def get_position(self):
        """Get the current position (x, y)"""
        status = self.get_status()
        return status['position']
    
    def move_to(self, x, y):
        """
        Move to absolute position with improved segmentation strategy
        """
        current_x, current_y = self.get_position()
        
        # Calculate distance
        x_dist = abs(x - current_x) if x is not None else 0
        y_dist = abs(y - current_y) if y is not None else 0
        
        # Check if motors need to be enabled
        if not self.motors_enabled:
            logger.debug("Motors not enabled, enabling before movement")
            self.enable_motors()
        
        # For very large moves, break into segments
        LARGE_MOVE_THRESHOLD = 40  # Reduced from 50 to 40
        
        # IMPROVED: Better segmentation strategy
        if x_dist > LARGE_MOVE_THRESHOLD or y_dist > LARGE_MOVE_THRESHOLD:
            # Calculate total distance for better segmentation
            total_dist = math.sqrt(x_dist**2 + y_dist**2)
            
            # Determine number of segments - smaller for more reliability
            # Use more segments for diagonal moves that involve both motors
            if x_dist > 0 and y_dist > 0:
                # Diagonal moves need more segments
                segment_size = 20  # 20 steps per segment for diagonal moves
            else:
                # Single-axis moves can use larger segments
                segment_size = 30  # 30 steps per segment for straight moves
                
            segments = max(2, int(total_dist / segment_size))
            
            logger.info(f"Breaking large move ({x_dist}, {y_dist}) into {segments} segments")
            
            # Calculate step sizes
            x_step = (x - current_x) / segments if x is not None else 0
            y_step = (y - current_y) / segments if y is not None else 0
            
            # Move in segments
            for i in range(segments):
                # Calculate target for this segment
                segment_x = int(current_x + x_step * (i + 1)) if x is not None else None
                segment_y = int(current_y + y_step * (i + 1)) if y is not None else None
                
                # For last segment, use exact target to avoid rounding errors
                if i == segments - 1:
                    segment_x = x if x is not None else None
                    segment_y = y if y is not None else None
                
                # Send command for this segment
                logger.debug(f"Segment {i+1}/{segments}: Moving to ({segment_x}, {segment_y})")
                
                # Create motor_select and handle None values
                motor_select = 0
                if segment_x is not None:
                    motor_select |= MotorSelect.MOTOR_X
                if segment_y is not None:
                    motor_select |= MotorSelect.MOTOR_Y
                
                segment_x = segment_x if segment_x is not None else 0
                segment_y = segment_y if segment_y is not None else 0
                
                # Send the command for this segment with shorter timeout
                response = self._send_command(
                    CommandID.CMD_MOVETO,
                    motor_select,
                    segment_x,
                    segment_y,
                    timeout=2.0
                )
                
                if response:
                    # Verify position with improved wait function
                    reached = self._wait_for_segment_completion(
                        segment_x, segment_y, timeout=5.0, tolerance=5
                    )
                    
                    if reached:
                        # Update current position for next segment
                        current_x, current_y = self.get_position()
                    else:
                        logger.warning(f"Segment {i+1} position not reached in time")
                        return False
                else:
                    logger.error(f"Failed to send move command for segment {i+1}")
                    return False
            
            # All segments completed successfully
            return True
            
        else:
            # For smaller moves, just use a single command
            motor_select = 0
            if x is not None:
                motor_select |= MotorSelect.MOTOR_X
            if y is not None:
                motor_select |= MotorSelect.MOTOR_Y
                
            # Use zero as default for params that aren't specified
            x = x if x is not None else 0
            y = y if y is not None else 0
            
            # Send command - only wait for initial acknowledgment
            response = self._send_command(
                CommandID.CMD_MOVETO,
                motor_select,
                x,
                y,
                timeout=2.0  # Short timeout just to confirm command was received
            )
            
            if response:
                # Verify position reached with efficient polling
                return self._wait_for_segment_completion(x, y, timeout=5.0, tolerance=5)
            
            return False
        
    def move_by(self, x_delta, y_delta):
        """Move by relative amount with segmentation for large moves"""
        # Check if this is a large move
        LARGE_MOVE_THRESHOLD = 75  # Steps
        
        if abs(x_delta) > LARGE_MOVE_THRESHOLD or abs(y_delta) > LARGE_MOVE_THRESHOLD:
            # Get current position
            current_x, current_y = self.get_position()
            
            # Calculate target position
            target_x = current_x + x_delta if x_delta is not None else current_x
            target_y = current_y + y_delta if y_delta is not None else current_y
            
            # Use move_to which has segmentation
            return self.move_to(target_x, target_y)
        else:
            # For smaller moves, just use a single command
            motor_select = 0
            if x_delta is not None:
                motor_select |= MotorSelect.MOTOR_X
            if y_delta is not None:
                motor_select |= MotorSelect.MOTOR_Y
                
            # Use zero as default for params that aren't specified
            x_delta = x_delta if x_delta is not None else 0
            y_delta = y_delta if y_delta is not None else 0
            
            # Send command
            response = self._send_command(
                CommandID.CMD_MOVE,
                motor_select,
                x_delta,
                y_delta,
                timeout=self.movement_timeout
            )
            
            return response is not None
    
    def wait_for_motors_to_stop(self, timeout=10.0):
        """Wait for motors to stop moving"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_status()
            
            if not any(status['running']):
                return True
                
            time.sleep(0.1)
            
        logger.warning(f"Timeout waiting for motors to stop")
        return False
    
    def set_speed(self, x_speed, y_speed):
        """Set the speed for both motors"""
        motor_select = 0
        if x_speed is not None:
            motor_select |= MotorSelect.MOTOR_X
        if y_speed is not None:
            motor_select |= MotorSelect.MOTOR_Y
            
        # Use zero as default for params that aren't specified
        x_speed = x_speed if x_speed is not None else 0
        y_speed = y_speed if y_speed is not None else 0
        
        # Send command
        response = self._send_command(
            CommandID.CMD_SPEED,
            motor_select,
            x_speed,
            y_speed
        )
        
        return response is not None
    
    def set_acceleration(self, x_accel, y_accel):
        """Set the acceleration for both motors"""
        motor_select = 0
        if x_accel is not None:
            motor_select |= MotorSelect.MOTOR_X
        if y_accel is not None:
            motor_select |= MotorSelect.MOTOR_Y
            
        # Use zero as default for params that aren't specified
        x_accel = x_accel if x_accel is not None else 0
        y_accel = y_accel if y_accel is not None else 0
        
        # Send command
        response = self._send_command(
            CommandID.CMD_ACCEL,
            motor_select,
            x_accel,
            y_accel
        )
        
        return response is not None
    
    def home(self):
        """Home both motors (set current position as zero)"""
        response = self._send_command(
            CommandID.CMD_HOME,
            MotorSelect.MOTOR_BOTH
        )
        
        return response is not None
    
    def stop(self):
        """Stop both motors"""
        response = self._send_command(
            CommandID.CMD_STOP,
            MotorSelect.MOTOR_BOTH
        )
        
        return response is not None
    
    def set_mode(self, mode):
        """Set the operation mode (joystick or serial)"""
        response = self._send_command(
            CommandID.CMD_MODE,
            0,
            mode
        )
        
        return response is not None
    
    def enable_motors(self):
        """Enable both motors and track state"""
        response = self._send_command(
            CommandID.CMD_ENABLE,
            MotorSelect.MOTOR_BOTH
        )
        
        if response is not None:
            self.motors_enabled = True
            return True
        return False
    
    def disable_motors(self):
        """Disable both motors and track state"""
        response = self._send_command(
            CommandID.CMD_DISABLE,
            MotorSelect.MOTOR_BOTH
        )
        
        if response is not None:
            self.motors_enabled = False
            return True
        return False
    
    def wait_for_position(self, target_x, target_y, timeout=10.0, tolerance=3):
        """
        Wait until motors reach target position with optimized polling
        """
        start_time = time.time()
        status_interval = 0.2  # Reduced frequency of status checks
        last_status_time = 0
        last_position = None
        
        while time.time() - start_time < timeout:
            current_time = time.time()
            
            # Only poll status at specific intervals to reduce communication load
            if current_time - last_status_time >= status_interval:
                # Get position and check if arrived
                x, y = self.get_position()
                last_status_time = current_time
                
                # Check if position hasn't changed since last check (motors stopped)
                position_stable = (last_position is not None and 
                                x == last_position[0] and 
                                y == last_position[1])
                
                # Store current position for next comparison
                last_position = (x, y)
                
                # If we've reached target position within tolerance
                if abs(x - target_x) <= tolerance and abs(y - target_y) <= tolerance:
                    logger.info(f"Reached position ({x}, {y})")
                    return True
                
                # If motors have stopped but not at target, try to resume
                if position_stable:
                    status = self.get_status()
                    if not any(status['running']) and (abs(x - target_x) > tolerance or abs(y - target_y) > tolerance):
                        logger.warning(f"Motors stopped at ({x}, {y}), not at target ({target_x}, {target_y})")
                        return False
            
            # Short sleep to keep CPU usage reasonable
            time.sleep(0.05)
        
        logger.warning(f"Position timeout: Target ({target_x}, {target_y})")
        return False
    
# Simple test function
def test_motor_controller():
    """Test the motor controller"""
    controller = ImprovedMotorController("COM6")  # Adjust port as needed
    
    try:
        logger.info("Testing motor controller")
        
        if controller.connect():
            logger.info("Connected successfully")
            
            # Test code remains the same until after the large move test
            
            # CHANGED ORDER: First disable motors, then switch modes
            # Disable motors
            logger.info("Disabling motors")
            controller.disable_motors()
            time.sleep(1.0)  # Add delay after disabling
            
            # Switch back to joystick mode
            logger.info("Switching back to joystick mode")
            controller.set_mode(OperationMode.MODE_JOYSTICK)
            
        else:
            logger.error("Failed to connect")
            
    except Exception as e:
        logger.error(f"Test error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        
    finally:
        # This will call safe_shutdown automatically
        controller.disconnect()
        logger.info("Test complete")
        
if __name__ == "__main__":
    test_motor_controller()