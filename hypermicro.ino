/**
 * Minimal Arduino Motor Controller
 * Controls two BYJ48 stepper motors with efficient communication protocol
 * 
 * Features:
 * - Precise motor control with AccelStepper
 * - Efficient binary communication with SerialTransfer
 * - Auto-disable motors when inactive
 * - Position reached notifications
 */

 #include <AccelStepper.h>
 #include <SerialTransfer.h>
 
 //=============================================================================
 // CONFIGURATION & PARAMETERS
 //=============================================================================
 
 // Pin Definitions
 #define MOTOR1_PIN1 8   // X-axis motor pins
 #define MOTOR1_PIN2 9
 #define MOTOR1_PIN3 10
 #define MOTOR1_PIN4 11
 
 #define MOTOR2_PIN1 4   // Y-axis motor pins
 #define MOTOR2_PIN2 5
 #define MOTOR2_PIN3 6
 #define MOTOR2_PIN4 7
 
 // Motor Parameters
 #define STEP_MODE 8     // 4 = HALF_STEP (higher resolution), 8 = FULL_STEP (more torque)
 #define DEFAULT_SPEED 800
 #define DEFAULT_ACCEL 1000
 #define INACTIVITY_TIMEOUT 200  // milliseconds of inactivity before motors disable
 #define INVERT_MOTOR1_DIRECTION false  // Set to true to invert X-axis direction
 #define INVERT_MOTOR2_DIRECTION false   // Set to true to invert Y-axis direction
 #define MOTOR1_SCALING_FACTOR 0.6  // X-axis scaling (1.0 = normal, no adjustment)
 #define MOTOR2_SCALING_FACTOR 1.0  // Y-axis scaling (e.g., 0.9 = 90% of requested movement)
 int32_t xBacklash = 15;      // Backlash amount in steps for X axis
 int32_t yBacklash = 15;      // Backlash amount in steps for Y axis
 bool xInBacklashComp = false;     // Flag for when we're in compensation phase
 bool yInBacklashComp = false;     // Flag for when we're in compensation phase
 bool backlashCompEnabled = true;  // Toggle for enabling/disabling compensation
 
 // FUTURE: Movement queue parameters
 // #define QUEUE_SIZE 10

//=============================================================================
// JOYSTICK CONFIGURATION
//=============================================================================

// Pin Definitions
#define JOYSTICK_X_PIN    A0   // Analog pin for X-axis
#define JOYSTICK_Y_PIN    A1   // Analog pin for Y-axis
#define JOYSTICK_BTN_PIN  2    // Digital pin for joystick button

// Joystick Parameters
#define JOYSTICK_CENTER      512   // Center value for analog reading (typically 512)
#define JOYSTICK_DEADZONE    25    // Deadzone around center to prevent drift
#define JOYSTICK_MIN_SPEED   10    // Minimum speed when just outside deadzone
#define JOYSTICK_MAX_SPEED   600   // Maximum speed at full joystick deflection
#define JOYSTICK_EXPO_FACTOR 2.0

// System Mode
#define MODE_SERIAL    0    // Control via serial commands
#define MODE_JOYSTICK  1    // Control via joystick

// Button debounce and long press detection
#define DEBOUNCE_TIME     50    // Debounce time in milliseconds
#define LONG_PRESS_TIME   1000  // Time threshold for long press in milliseconds

 //=============================================================================
 // SYSTEM PARAMETERS
 //=============================================================================

// Command IDs
#define CMD_MOVE_TO 0x01
#define CMD_SET_SPEED 0x03
#define CMD_SET_ACCEL 0x04
#define CMD_STOP 0x05
#define CMD_HOME 0x06
#define CMD_ENABLE 0x07
#define CMD_DISABLE 0x08
#define CMD_GET_STATUS 0x09
#define CMD_PING 0x0A
#define CMD_SET_MODE 0x0B
#define CMD_SET_BACKLASH 0x0C

// Response IDs
#define RESP_OK 0x81
#define RESP_ERROR 0x82
#define RESP_POSITION_REACHED 0x84
#define RESP_PING 0x86

// Error Codes
#define ERR_INVALID_COMMAND 0x01
#define ERR_INVALID_PARAMETER 0x02
#define ERR_COMMAND_FAILED 0x03

// System State
#define STATE_IDLE 0
#define STATE_MOVING 1
#define STATE_ERROR 2

 //=============================================================================
 // GLOBAL VARIABLES
 //=============================================================================
 
// Communication
SerialTransfer myTransfer;
bool commandReceived = false;
 
// Motor Control
AccelStepper stepper1(STEP_MODE, MOTOR1_PIN1, MOTOR1_PIN3, MOTOR1_PIN2, MOTOR1_PIN4); // X-axis
AccelStepper stepper2(STEP_MODE, MOTOR2_PIN1, MOTOR2_PIN3, MOTOR2_PIN2, MOTOR2_PIN4); // Y-axis
 
// State tracking
uint8_t systemState = STATE_IDLE;
bool motorsEnabled = false;
unsigned long lastActivityTime = 0;
uint16_t currentSequenceId = 0;
bool positionReached = false;
uint8_t currentMode = MODE_SERIAL; // MODE_SERIAL vs MODE_JOYSTICK

// Joystick state
int joystickXValue = JOYSTICK_CENTER;
int joystickYValue = JOYSTICK_CENTER;
int motorXSpeed = 0;  // Current X speed derived from joystick
int motorYSpeed = 0;  // Current Y speed derived from joystick
unsigned long lastJoystickCheckTime = 0;  // For throttling joystick checks

// Button state
bool buttonPressed = false;
bool buttonState = false;
bool lastButtonState = false;
unsigned long lastButtonChangeTime = 0;
unsigned long buttonPressStartTime = 0;

// Joystick activity tracking
bool joystickActive = false;
unsigned long lastJoystickActivity = 0;

// Backlash Compensation
int32_t lastXDirection = 0;  // -1 for negative, 1 for positive, 0 for first move
int32_t lastYDirection = 0;
int32_t xFinalTarget = 0;         // The actual target after compensation
int32_t yFinalTarget = 0;         // The actual target after compensation
 
 // FUTURE: Movement queue
 // struct MovementQueueEntry {
 //   int32_t xPos;
 //   int32_t yPos;
 //   uint16_t sequenceId;
 // };
 // MovementQueueEntry movementQueue[QUEUE_SIZE];
 // uint8_t queueHead = 0;
 // uint8_t queueTail = 0;

 //=============================================================================
 // COMMUNICATION MODULE
 //=============================================================================
 
 /**
  * Process incoming command from SerialTransfer
  */
 void processCommand() {
   // Extract command ID (first byte)
   uint8_t commandId = myTransfer.packet.rxBuff[0];
 
   // Process based on command type
   switch (commandId) {
     
     case CMD_MOVE_TO:
       // Extract parameters: X position (4 bytes), Y position (4 bytes), Sequence ID (2 bytes)
       int32_t xPos, yPos;
       uint16_t sequenceId;
       
       memcpy(&xPos, &myTransfer.packet.rxBuff[1], sizeof(xPos));
       memcpy(&yPos, &myTransfer.packet.rxBuff[5], sizeof(yPos));
       memcpy(&sequenceId, &myTransfer.packet.rxBuff[9], sizeof(sequenceId));
       
       // Move to the requested position
       if (moveToPosition(xPos, yPos, sequenceId)) {
         sendOkResponse(commandId);
       } else {
         sendError(commandId, ERR_COMMAND_FAILED);
       }
       break;
     
     case CMD_SET_SPEED:
       // Extract parameters: X speed (2 bytes), Y speed (2 bytes)
       uint16_t xSpeed, ySpeed;
       
       memcpy(&xSpeed, &myTransfer.packet.rxBuff[1], sizeof(xSpeed));
       memcpy(&ySpeed, &myTransfer.packet.rxBuff[3], sizeof(ySpeed));
       
       // Set motor speeds (apply scaling factors)
       stepper1.setMaxSpeed(xSpeed * MOTOR1_SCALING_FACTOR);
       stepper2.setMaxSpeed(ySpeed * MOTOR2_SCALING_FACTOR);
       sendOkResponse(commandId);
       break;
       
     case CMD_SET_ACCEL:
       // Extract parameters: X accel (2 bytes), Y accel (2 bytes)
       uint16_t xAccel, yAccel;
       
       memcpy(&xAccel, &myTransfer.packet.rxBuff[1], sizeof(xAccel));
       memcpy(&yAccel, &myTransfer.packet.rxBuff[3], sizeof(yAccel));
       
       // Set motor acceleration (apply scaling factors)
       stepper1.setAcceleration(xAccel * MOTOR1_SCALING_FACTOR);
       stepper2.setAcceleration(yAccel * MOTOR2_SCALING_FACTOR);
       sendOkResponse(commandId);
       break;
       
     case CMD_STOP:
       // Stop all motors
       stepper1.stop();
       stepper2.stop();
       systemState = STATE_IDLE;
       sendOkResponse(commandId);
       break;
       
     case CMD_HOME:
       // Set current position as zero
       stepper1.setCurrentPosition(0);
       stepper2.setCurrentPosition(0);
       sendOkResponse(commandId);
       break;
       
     case CMD_ENABLE:
       // Enable motors
       enableMotors();
       sendOkResponse(commandId);
       break;
       
     case CMD_DISABLE:
       // Disable motors
       disableMotors();
       sendOkResponse(commandId);
       break;
       
     case CMD_GET_STATUS:
       // Send current status
       sendStatus();
       break;

     case CMD_SET_BACKLASH:
       // Extract parameters: X backlash (2 bytes), Y backlash (2 bytes), Enable flag (1 byte)
       uint16_t xBacklashNew, yBacklashNew;
       uint8_t enableFlag;
       
       memcpy(&xBacklashNew, &myTransfer.packet.rxBuff[1], sizeof(xBacklashNew));
       memcpy(&yBacklashNew, &myTransfer.packet.rxBuff[3], sizeof(yBacklashNew));
       enableFlag = myTransfer.packet.rxBuff[5];
       
       // Update backlash parameters
       xBacklash = xBacklashNew;
       yBacklash = yBacklashNew;
       backlashCompEnabled = (enableFlag > 0);
       
       sendOkResponse(commandId);
       break;
       
     case CMD_PING:
       // Extract echo value (4 bytes)
       uint32_t echoValue;
       memcpy(&echoValue, &myTransfer.packet.rxBuff[1], sizeof(echoValue));
       
       // Send ping response
       sendPingResponse(echoValue);
       break;

       case CMD_SET_MODE:
       // Extract mode parameter
       uint8_t newMode = myTransfer.packet.rxBuff[1];
       
       // Validate mode
       if (newMode == MODE_SERIAL || newMode == MODE_JOYSTICK) {
         setMode(newMode);
         sendOkResponse(commandId);
       } else {
         sendError(commandId, ERR_INVALID_PARAMETER);
       }
       break;
       
     default:
       // Unknown command
       sendError(commandId, ERR_INVALID_COMMAND);
       break;
   }
   
   // Reset command received flag
   commandReceived = false;
 }
 
 /**
  * Send OK response
  */
 void sendOkResponse(uint8_t commandId) {
   myTransfer.packet.txBuff[0] = RESP_OK;
   myTransfer.packet.txBuff[1] = commandId;
   
   // Send 2 bytes
   myTransfer.sendData(2);
 }
 
 /**
  * Send error response
  */
 void sendError(uint8_t commandId, uint8_t errorCode) {
  // Clear the packet buffer to avoid any undefined behavior
  for (uint8_t i = 0; i < 8; i++) {
    myTransfer.packet.txBuff[i] = 0;
  }
  
  // Set response values
  myTransfer.packet.txBuff[0] = RESP_ERROR;
  myTransfer.packet.txBuff[1] = commandId;
  myTransfer.packet.txBuff[2] = errorCode;
  
  // Send 3 bytes - guaranteed size for error response
  uint8_t sendResult = myTransfer.sendData(3);
  
  // Delay BEFORE second attempt to ensure Arduino has time to process
  delay(5);
  
  // Always send a second time for reliability (fixed timing issue)
  myTransfer.sendData(3);
}

 /**
  * Send position reached notification
  */
 void sendPositionReached(uint16_t sequenceId) {
   myTransfer.packet.txBuff[0] = RESP_POSITION_REACHED;
   
   // Sequence ID (2 bytes)
   memcpy(&myTransfer.packet.txBuff[1], &sequenceId, sizeof(sequenceId));
   
   // Current X position (4 bytes)
   int32_t xPos = stepper1.currentPosition();
   memcpy(&myTransfer.packet.txBuff[3], &xPos, sizeof(xPos));
   
   // Current Y position (4 bytes)
   int32_t yPos = stepper2.currentPosition();
   memcpy(&myTransfer.packet.txBuff[7], &yPos, sizeof(yPos));
   
   // Send 11 bytes
   myTransfer.sendData(11);
   
   // Reset position reached flag
   positionReached = false;
 }
 
 /**
  * Send status response
  */
 void sendStatus() {
   // First make sure all bytes are properly initialized to avoid any undefined behavior
   for (uint8_t i = 0; i < 16; i++) {
     myTransfer.packet.txBuff[i] = 0;
   }
   
   // Response ID and command echo
   myTransfer.packet.txBuff[0] = RESP_OK;
   myTransfer.packet.txBuff[1] = CMD_GET_STATUS;
   
   // Current X position (4 bytes)
   int32_t xPos = stepper1.currentPosition();
   memcpy(&myTransfer.packet.txBuff[2], &xPos, sizeof(xPos));
   
   // Current Y position (4 bytes)
   int32_t yPos = stepper2.currentPosition();
   memcpy(&myTransfer.packet.txBuff[6], &yPos, sizeof(yPos));
   
   // Running state (1 byte)
   uint8_t runningState = 0;
   if (stepper1.isRunning()) runningState |= 0x01;
   if (stepper2.isRunning()) runningState |= 0x02;
   myTransfer.packet.txBuff[10] = runningState;
   
   // Motor enabled state (1 byte)
   myTransfer.packet.txBuff[11] = motorsEnabled ? 1 : 0;
   
   // System state (1 byte)
   myTransfer.packet.txBuff[12] = systemState;
   
   // FUTURE: Queue state
   // myTransfer.packet.txBuff[13] = queueHead;
   // myTransfer.packet.txBuff[14] = queueTail;
   // uint8_t queueSize = (queueTail >= queueHead) ? (queueTail - queueHead) : (QUEUE_SIZE - queueHead + queueTail);
   // myTransfer.packet.txBuff[15] = queueSize;
   
   // Send status data (13 bytes)
   uint8_t size = 13;
   
   // Send the data and verify successful transmission
   uint8_t sendResult = myTransfer.sendData(size);
   
   // For troubleshooting purposes
   // If this fails, we would need to add additional error handling
   if (sendResult == 0) {
     // Failed to send - could add error indicator here
   }
 }
 
 /**
  * Send ping response
  */
 void sendPingResponse(uint32_t echoValue) {
   myTransfer.packet.txBuff[0] = RESP_PING;
   
   // Echo value (4 bytes)
   memcpy(&myTransfer.packet.txBuff[1], &echoValue, sizeof(echoValue));
   
   // Send 5 bytes
   myTransfer.sendData(5);
 }
 
 //=============================================================================
 // MOTOR CONTROL MODULE
 //=============================================================================
 
 /**
  * Enable both motors
  */
 void enableMotors() {
   stepper1.enableOutputs();
   stepper2.enableOutputs();
   motorsEnabled = true;
   lastActivityTime = millis(); // Reset inactivity timer
 }
 
 /**
  * Disable both motors
  */
 void disableMotors() {
   stepper1.disableOutputs();
   stepper2.disableOutputs();
   motorsEnabled = false;
 }
 
 /**
  * Check for motor inactivity and disable if needed
  */
 void checkInactivity() {
   // If motors are enabled and not moving
   if (motorsEnabled && !stepper1.isRunning() && !stepper2.isRunning()) {
     // Check if inactivity timeout has elapsed
     if (millis() - lastActivityTime > INACTIVITY_TIMEOUT) {
       disableMotors();
       // FUTURE: Log motor disable event
       // logEvent(EVENT_MOTOR_DISABLED);
     }
   }
 }
 
 /**
  * Convert external coordinate space to internal motor coordinate space
  * This applies scaling factors for motors with different physical characteristics
  */

 int32_t scaleXPosition(int32_t x) {
   return x * MOTOR1_SCALING_FACTOR;
 }

 int32_t scaleYPosition(int32_t y) {
   return y * MOTOR2_SCALING_FACTOR;
 }
 
 /**
  * Move to specified position
  */

  bool moveToPosition(int32_t x, int32_t y, uint16_t sequenceId) {
    // Store sequence ID for position reached notification
    currentSequenceId = sequenceId;
    
    // Ensure motors are enabled
    if (!motorsEnabled) {
      enableMotors();
    }
    
    // Apply scaling factors to the target positions
    int32_t scaledX = scaleXPosition(x);
    int32_t scaledY = scaleYPosition(y);
    
    // Calculate current position
    int32_t currentX = stepper1.currentPosition();
    int32_t currentY = stepper2.currentPosition();
    
    // Determine movement direction
    int32_t newXDirection = 0;
    if (scaledX > currentX) newXDirection = 1;
    else if (scaledX < currentX) newXDirection = -1;
    
    int32_t newYDirection = 0;
    if (scaledY > currentY) newYDirection = 1;
    else if (scaledY < currentY) newYDirection = -1;
    
    // Apply backlash compensation if enabled
    if (backlashCompEnabled) {
      // Only apply on direction changes
      if (lastXDirection != 0 && newXDirection != 0 && newXDirection != lastXDirection) {
        // Take a step larger than the backlash to take up the slack
        int32_t firstMoveX = currentX + (newXDirection * (abs(scaledX - currentX) + xBacklash));
        
        // Set the temporary target with backlash compensation
        #if INVERT_MOTOR1_DIRECTION
          stepper1.moveTo(-firstMoveX);
        #else
          stepper1.moveTo(firstMoveX);
        #endif
        
        // Run the motor until this position is reached
        while (stepper1.distanceToGo() != 0) {
          stepper1.run();
        }
        
        // IMPORTANT: Now set the actual target position
        #if INVERT_MOTOR1_DIRECTION
          stepper1.moveTo(-scaledX);
        #else
          stepper1.moveTo(scaledX);
        #endif
      }
      else {
        // No direction change, just set target normally
        #if INVERT_MOTOR1_DIRECTION
          stepper1.moveTo(-scaledX);
        #else
          stepper1.moveTo(scaledX);
        #endif
      }
      
      // Same for Y-axis
      if (lastYDirection != 0 && newYDirection != 0 && newYDirection != lastYDirection) {
        int32_t firstMoveY = currentY + (newYDirection * (abs(scaledY - currentY) + yBacklash));
        
        #if INVERT_MOTOR2_DIRECTION
          stepper2.moveTo(-firstMoveY);
        #else
          stepper2.moveTo(firstMoveY);
        #endif
        
        while (stepper2.distanceToGo() != 0) {
          stepper2.run();
        }
        
        #if INVERT_MOTOR2_DIRECTION
          stepper2.moveTo(-scaledY);
        #else
          stepper2.moveTo(scaledY);
        #endif
      }
      else {
        #if INVERT_MOTOR2_DIRECTION
          stepper2.moveTo(-scaledY);
        #else
          stepper2.moveTo(scaledY);
        #endif
      }
      
      // Remember current directions for next time
      if (newXDirection != 0) lastXDirection = newXDirection;
      if (newYDirection != 0) lastYDirection = newYDirection;
    }
    else {
      // Backlash compensation disabled, just set targets normally
      #if INVERT_MOTOR1_DIRECTION
        stepper1.moveTo(-scaledX);
      #else
        stepper1.moveTo(scaledX);
      #endif
      
      #if INVERT_MOTOR2_DIRECTION
        stepper2.moveTo(-scaledY);
      #else
        stepper2.moveTo(scaledY);
      #endif
    }
    
    // Update activity time and state
    lastActivityTime = millis();
    systemState = STATE_MOVING;
    positionReached = false;
    
    return true;
  }

 /**
  * Update motor positions and check for completion
  */
 void updateMotors() {
  // Only update if motors are running
  bool motor1Running = stepper1.isRunning();
  bool motor2Running = stepper2.isRunning();
  
  if (motor1Running || motor2Running) {
    // Check if we need to handle backlash compensation phases
    if (xInBacklashComp && !motor1Running) {
      // X motor has finished backlash compensation phase
      // Now move to the actual target
      #if INVERT_MOTOR1_DIRECTION
        stepper1.moveTo(-xFinalTarget);
      #else
        stepper1.moveTo(xFinalTarget);
      #endif
      xInBacklashComp = false;
    }
    
    if (yInBacklashComp && !motor2Running) {
      // Y motor has finished backlash compensation phase
      // Now move to the actual target
      #if INVERT_MOTOR2_DIRECTION
        stepper2.moveTo(-yFinalTarget);
      #else
        stepper2.moveTo(yFinalTarget);
      #endif
      yInBacklashComp = false;
    }
    
    // Run the motors
    if (motor1Running) stepper1.run();
    if (motor2Running) stepper2.run();
    
    // Update activity time
    lastActivityTime = millis();
  }
  else if (systemState == STATE_MOVING && !positionReached) {
    // Motors have stopped and we were in moving state
    // This means we've reached the target position
    systemState = STATE_IDLE;
    positionReached = true;
  }
}

 // FUTURE: Movement queue functions
 /* 
 void enqueueMovement(int32_t x, int32_t y, uint16_t sequenceId) {
   // Check if queue is full
   uint8_t nextTail = (queueTail + 1) % QUEUE_SIZE;
   if (nextTail == queueHead) {
     // Queue is full
     sendError(CMD_MOVE_TO, ERR_QUEUE_FULL);
     return false;
   }
   
   // Add to queue
   movementQueue[queueTail].xPos = x;
   movementQueue[queueTail].yPos = y;
   movementQueue[queueTail].sequenceId = sequenceId;
   queueTail = nextTail;
   
   // If not currently moving, start the first queued movement
   if (systemState != STATE_MOVING) {
     processNextQueuedMovement();
   }
   
   return true;
 }
 
 void processNextQueuedMovement() {
   // Check if queue is empty
   if (queueHead == queueTail) {
     // Nothing in queue
     return;
   }
   
   // Get next movement from queue
   MovementQueueEntry* entry = &movementQueue[queueHead];
   
   // Move to position
   moveToPosition(entry->xPos, entry->yPos, entry->sequenceId);
   
   // Advance queue head
   queueHead = (queueHead + 1) % QUEUE_SIZE;
 }
 */
 
 // FUTURE: Thermal management
 /*
 unsigned long movementStartTime = 0;
 unsigned long totalMovementTime = 0;
 float dutyRatio = 0.0;
 
 void updateThermalEstimate() {
   // Calculate duty cycle as proportion of time motors were running
   unsigned long currentTime = millis();
   unsigned long elapsedTime = currentTime - movementStartTime;
   
   if (elapsedTime > 10000) { // Update every 10 seconds
     // Calculate duty ratio (0.0 - 1.0)
     dutyRatio = min(1.0, (float)totalMovementTime / elapsedTime);
     
     // Reset counters
     movementStartTime = currentTime;
     totalMovementTime = 0;
     
     // If duty cycle too high, enforce cooling period
     if (dutyRatio > 0.8) { // 80% duty cycle
       // Add cooling delay
       delay(1000); // Force 1 second cooling period
     }
   }
   
   // Update movement time counter if motors are running
   if (stepper1.isRunning() || stepper2.isRunning()) {
     totalMovementTime += 5; // Approximate run time in this loop cycle
   }
 }
 */
 
//=============================================================================
// JOYSTICK CONTROL MODULE
//=============================================================================

/**
 * Apply exponential curve to joystick input
 * 
 * This gives more precision at the lower end of the range
 * while still maintaining full speed at maximum deflection.
 * 
 * Input values should be normalized from 0.0 to 1.0.
 */
float applyExponentialCurve(float normalizedInput) {
  // Apply exponential curve (input^expoFactor)
  return pow(normalizedInput, JOYSTICK_EXPO_FACTOR);
}

/**
 * Initialize joystick
 */
void initJoystick() {
  // Set pin modes
  pinMode(JOYSTICK_X_PIN, INPUT);
  pinMode(JOYSTICK_Y_PIN, INPUT);
  pinMode(JOYSTICK_BTN_PIN, INPUT_PULLUP);  // Using internal pull-up resistor
  
  // Initialize state
  joystickXValue = analogRead(JOYSTICK_X_PIN);
  joystickYValue = analogRead(JOYSTICK_Y_PIN);
  buttonState = digitalRead(JOYSTICK_BTN_PIN);
  lastButtonState = buttonState;
}

/**
 * Read joystick values and calculate motor speeds.
 * Returns true if joystick is active (out of deadzone)
 */
bool handleJoystick() {
  // Only process if in joystick mode
  if (currentMode != MODE_JOYSTICK) {
    return false;
  }
  
  // Read joystick values
  int joyX = analogRead(JOYSTICK_X_PIN);
  int joyY = analogRead(JOYSTICK_Y_PIN);
  
  // Calculate X motor speed with exponential curve
  int prevMotorXSpeed = motorXSpeed;
  if (abs(joyX - JOYSTICK_CENTER) > JOYSTICK_DEADZONE) {
    int xOffset = joyX - JOYSTICK_CENTER;
    
    // Calculate deflection ratio (0.0 to 1.0) based on max possible deflection
    float xDeflection = (float)abs(xOffset) - JOYSTICK_DEADZONE;
    float maxDeflection = 512.0 - JOYSTICK_DEADZONE; // Maximum possible deflection
    float normalizedX = xDeflection / maxDeflection;
    
    // Clamp to valid range
    normalizedX = max(0.0f, min(1.0f, normalizedX));
    
    // Apply exponential curve to normalized value
    float expoCurvedX = applyExponentialCurve(normalizedX);
    
    // Map curved value back to speed range
    motorXSpeed = JOYSTICK_MIN_SPEED + (JOYSTICK_MAX_SPEED - JOYSTICK_MIN_SPEED) * expoCurvedX;
    
    // Apply direction
    motorXSpeed = xOffset > 0 ? motorXSpeed : -motorXSpeed;
    
    // Apply scaling factor
    motorXSpeed = motorXSpeed * MOTOR1_SCALING_FACTOR;
    
    // Apply direction inversion if configured
    #if INVERT_MOTOR1_DIRECTION
      motorXSpeed = -motorXSpeed;
    #endif
  } else {
    motorXSpeed = 0;
  }
  
  // Calculate Y motor speed with exponential curve
  int prevMotorYSpeed = motorYSpeed;
  if (abs(joyY - JOYSTICK_CENTER) > JOYSTICK_DEADZONE) {
    int yOffset = joyY - JOYSTICK_CENTER;
    
    // Calculate deflection ratio (0.0 to 1.0) based on max possible deflection
    float yDeflection = (float)abs(yOffset) - JOYSTICK_DEADZONE;
    float maxDeflection = 512.0 - JOYSTICK_DEADZONE; // Maximum possible deflection
    float normalizedY = yDeflection / maxDeflection;
    
    // Clamp to valid range
    normalizedY = max(0.0f, min(1.0f, normalizedY));
    
    // Apply exponential curve to normalized value
    float expoCurvedY = applyExponentialCurve(normalizedY);
    
    // Map curved value back to speed range
    motorYSpeed = JOYSTICK_MIN_SPEED + (JOYSTICK_MAX_SPEED - JOYSTICK_MIN_SPEED) * expoCurvedY;
    
    // Apply direction
    motorYSpeed = yOffset > 0 ? motorYSpeed : -motorYSpeed;
    
    // Apply scaling factor
    motorYSpeed = motorYSpeed * MOTOR2_SCALING_FACTOR;
    
    // Apply direction inversion if configured
    #if INVERT_MOTOR2_DIRECTION
      motorYSpeed = -motorYSpeed;
    #endif
  } else {
    motorYSpeed = 0;
  }
  
  // Check if joystick is active
  bool joystickMoved = (motorXSpeed != 0 || motorYSpeed != 0 || 
                        motorXSpeed != prevMotorXSpeed || motorYSpeed != prevMotorYSpeed);
  
  // Process button input
  processJoystickButton();
  
  // Run motors if there's movement
  if (motorXSpeed != 0 || motorYSpeed != 0) {
    if (!motorsEnabled) {
      enableMotors();
    }
    
    // For continuous rotation, we need to use runSpeed
    // This runs the motor at a constant speed without acceleration
    stepper1.setSpeed(motorXSpeed);
    stepper2.setSpeed(motorYSpeed);
    
    // Run one step at the set speed
    // This is important - we need to call these in each loop iteration
    if (motorXSpeed != 0) stepper1.runSpeed();
    if (motorYSpeed != 0) stepper2.runSpeed();
    
    // Update activity timers
    lastActivityTime = millis();
    lastJoystickActivity = millis();
    joystickActive = true;
  } else {
    // No movement
    if (joystickActive) {
      // We just stopped - mark the time
      lastJoystickActivity = millis();
      joystickActive = false;
    }
  }
  
  return joystickMoved;
}

/**
 * Check for joystick inactivity and disable motors if needed
 */
void checkJoystickInactivity() {
  // Only check in joystick mode and when joystick is inactive but motors are enabled
  if (currentMode == MODE_JOYSTICK && !joystickActive && motorsEnabled) {
    // If enough time has passed since last joystick activity
    if (millis() - lastJoystickActivity > INACTIVITY_TIMEOUT) {
      disableMotors();
    }
  }
}

/**
 * Process joystick button input with debounce
 */
void processJoystickButton() {
  // Read the current button state
  bool currentReading = digitalRead(JOYSTICK_BTN_PIN);
  
  // Check if button state has changed
  if (currentReading != lastButtonState) {
    lastButtonChangeTime = millis();
  }
  
  // Check if button state is stable for debounce period
  if ((millis() - lastButtonChangeTime) > DEBOUNCE_TIME) {
    // If button state has changed since last stable reading
    if (currentReading != buttonState) {
      buttonState = currentReading;
      
      if (buttonState == LOW) {  // Button pressed (LOW due to pull-up)
        // Button just pressed
        buttonPressed = true;
        buttonPressStartTime = millis();
      } else {
        // Button just released
        // Check if it was a short press or long press
        unsigned long pressDuration = millis() - buttonPressStartTime;
        
        if (pressDuration < LONG_PRESS_TIME) {
          // Short press - toggle motors
          handleButtonShortPress();
        } else {
          // Long press - home
          handleButtonLongPress();
        }
        
        buttonPressed = false;
      }
    }
  }
  
  // Check for ongoing long press
  if (buttonPressed && buttonState == LOW) {
    // If button is still pressed and held down
    if ((millis() - buttonPressStartTime) > LONG_PRESS_TIME) {
      // Long press detected
      handleButtonLongPress();
      buttonPressed = false;  // Prevent repeated triggers
    }
  }
  
  // Update the last button state
  lastButtonState = currentReading;
}

/**
 * Handle joystick button short press
 */
void handleButtonShortPress() {
  // Toggle motors on/off
  if (motorsEnabled) {
    disableMotors();
  } else {
    enableMotors();
  }
}

/**
 * Handle joystick button long press
 */
void handleButtonLongPress() {
  // Home the motors (reset position to 0)
  stepper1.setCurrentPosition(0);
  stepper2.setCurrentPosition(0);
}

/**
 * Switch system mode
 */
void setMode(uint8_t newMode) {
  if (newMode == currentMode) {
    return;  // No change needed
  }
  
  // Stop any current movements
  stepper1.stop();
  stepper2.stop();
  
  // Switch mode
  currentMode = newMode;
  
  if (currentMode == MODE_JOYSTICK) {
    // Switching to joystick mode
    // Reset joystick speeds
    motorXSpeed = 0;
    motorYSpeed = 0;
    
    // Read initial joystick position
    joystickXValue = analogRead(JOYSTICK_X_PIN);
    joystickYValue = analogRead(JOYSTICK_Y_PIN);
    
    // Reset joystick activity tracking
    joystickActive = false;
    lastJoystickActivity = millis();
    
    // FUTURE: Clear movement queue here if implemented
    // clearMovementQueue();
  }
  else {
    // Switching to serial mode
    // Nothing special needed here, just stop joystick control
  }
  
  // For safety, motors need explicit enable
  disableMotors();
}

 //=============================================================================
 // SETUP & MAIN LOOP
 //=============================================================================
 
 void setup() {
  // Initialize communication
  Serial.begin(115200);
  myTransfer.begin(Serial);
  
  // Initialize motors
  stepper1.setMaxSpeed(DEFAULT_SPEED * MOTOR1_SCALING_FACTOR);
  stepper1.setAcceleration(DEFAULT_ACCEL * MOTOR1_SCALING_FACTOR);
  stepper2.setMaxSpeed(DEFAULT_SPEED * MOTOR2_SCALING_FACTOR);
  stepper2.setAcceleration(DEFAULT_ACCEL * MOTOR2_SCALING_FACTOR);
  
  // Initialize joystick
  initJoystick();
  
  // Start with motors disabled
  disableMotors();
  
  // Initialize timers
  lastActivityTime = millis();
  
  // FUTURE: Initialize diagnostic features
  // initializeErrorLog();
  // initializePerformanceCounters();
  
  // Indicate system ready
  // FUTURE: Use onboard LED for status indication
  // digitalWrite(LED_BUILTIN, HIGH);
}

// Update the main loop to add auto-switching to joystick mode:
void loop() {
  // Check for incoming commands
  if (myTransfer.available()) {
    commandReceived = true;
  }
  
  // Process command if received
  if (commandReceived) {
    processCommand();
  }
  
  // Handle operation based on current mode
  if (currentMode == MODE_SERIAL) {
    // Serial control mode
    
    // Update motor positions
    updateMotors();
    
    // Check for position reached notification
    if (positionReached) {
      sendPositionReached(currentSequenceId);
    }
    
    // Check for idle joystick movement to auto-switch to joystick mode
    // But only check periodically to avoid constant analog reads
    unsigned long currentTime = millis();
    if (currentTime - lastJoystickCheckTime > 100) {  // Check every 100ms
      lastJoystickCheckTime = currentTime;
      
      // Only check for auto-switching if the system is idle (motors not running)
      if (!stepper1.isRunning() && !stepper2.isRunning()) {
        int xValue = analogRead(JOYSTICK_X_PIN);
        int yValue = analogRead(JOYSTICK_Y_PIN);
        
        // Check if joystick has moved significantly from center
        if (abs(xValue - JOYSTICK_CENTER) > JOYSTICK_DEADZONE * 1.5 || 
            abs(yValue - JOYSTICK_CENTER) > JOYSTICK_DEADZONE * 1.5) {
          // Joystick moved significantly - auto-switch to joystick mode
          setMode(MODE_JOYSTICK);
        }
      }
    }
  }
  else if (currentMode == MODE_JOYSTICK) {
    // Joystick control mode - use the revised joystick handler
    handleJoystick();
    
    // Specific inactivity check for joystick mode
    checkJoystickInactivity();
  }
  
  // Check for motor inactivity (applies to serial mode only)
  if (currentMode == MODE_SERIAL) {
    checkInactivity();
  }
  
  // FUTURE: Check thermal status
  // updateThermalEstimate();
  
  // Very small delay for stability
  delay(1);
}