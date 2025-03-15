#include <AccelStepper.h>
#include "SerialTransfer.h"

// Create SerialTransfer object
SerialTransfer myTransfer;

// Define pin connections for stepper motors
#define MOTOR1_IN1 8  // X axis
#define MOTOR1_IN2 9
#define MOTOR1_IN3 10
#define MOTOR1_IN4 11

#define MOTOR2_IN1 4  // Y axis
#define MOTOR2_IN2 5
#define MOTOR2_IN3 6
#define MOTOR2_IN4 7

// Define step mode
#define STEP_MODE 4  // FULLSTEP for higher torque

// Init stepper motors
AccelStepper stepper1(STEP_MODE, MOTOR1_IN1, MOTOR1_IN3, MOTOR1_IN2, MOTOR1_IN4); // X axis
AccelStepper stepper2(STEP_MODE, MOTOR2_IN1, MOTOR2_IN3, MOTOR2_IN2, MOTOR2_IN4); // Y axis

// Command IDs
enum CommandID {
  CMD_MOVE = 1,
  CMD_MOVETO = 2,
  CMD_SPEED = 3,
  CMD_ACCEL = 4,
  CMD_HOME = 5,
  CMD_STOP = 6,
  CMD_MODE = 7,
  CMD_STATUS = 8,
  CMD_DISABLE = 9,
  CMD_ENABLE = 10,
  CMD_PING = 11
};

// Response IDs
enum ResponseID {
  RESP_OK = 1,
  RESP_ERROR = 2,
  RESP_STATUS = 3,
  RESP_POSITION = 4,
  RESP_PING = 5
};

// Operation Modes
enum OperationMode {
  MODE_JOYSTICK = 0,
  MODE_SERIAL = 1
};

// Current state
uint8_t currentMode = MODE_JOYSTICK;
bool motorsEnabled = false;
uint16_t sequenceCounter = 0;

// Joystick variables
const int JOY_X_PIN = A0;
const int JOY_Y_PIN = A1;
const int JOY_SW_PIN = 2;
const int JOY_CENTER = 512;
const int DEADZONE = 50;

// Motor speed variables
int motor1Speed = 0;
int motor2Speed = 0;
int maxSpeed = 600;
int minSpeed = 50;

// Inactivity timers
unsigned long lastActivityTime = 0;
const unsigned long INACTIVITY_TIMEOUT = 2000;  // 10 seconds of inactivity before disabling motors
const unsigned long STATUS_INTERVAL = 1000;      // Send status update every second
unsigned long lastStatusTime = 0;

// Buffer and processing flags
bool isProcessingCommand = false;
bool needToProcessCommand = false;
unsigned long lastCommandTime = 0;
unsigned long COMMAND_SPACING = 200; // 200ms minimum between commands

// Flag for large moves
bool makingLargeMove = false;
const int LARGE_MOVE_THRESHOLD = 50; // Steps

void setup() {
  // Setup serial
  Serial.begin(115200);
  
  // Initialize SerialTransfer
  myTransfer.begin(Serial);
  
  // Initialize motors
  stepper1.setMaxSpeed(maxSpeed);
  stepper1.setAcceleration(1000);
  stepper2.setMaxSpeed(maxSpeed);
  stepper2.setAcceleration(1000);
  
  // Start with motors disabled
  stepper1.disableOutputs();
  stepper2.disableOutputs();
  
  // Initialize joystick button
  pinMode(JOY_SW_PIN, INPUT_PULLUP);
  
  Serial.println("Motor Controller Ready");
  
  // Initialize activity timer
  lastActivityTime = millis();
  lastCommandTime = millis();
}

void loop() {
  unsigned long currentTime = millis();
  
  // Check for new commands (but don't process if we're in the middle of something)
  if (myTransfer.available() && !isProcessingCommand) {
    isProcessingCommand = true;
    needToProcessCommand = true;
    lastCommandTime = currentTime;
  }
  
  // Process command if needed and enough time has passed since last command
  if (needToProcessCommand && (currentTime - lastCommandTime >= COMMAND_SPACING)) {
    processCommand();
    isProcessingCommand = false;
    needToProcessCommand = false;
  }
  
  // Handle motors based on mode
  if (currentMode == MODE_JOYSTICK) {
    // Joystick control
    if (handleJoystick()) {
      lastActivityTime = currentTime;  // Update activity timer on joystick movement
    }
  } else {
    // Serial control - update step motors
    bool moving = stepper1.isRunning() || stepper2.isRunning();
    if (moving) {
      
      // For large moves, only run a few steps at a time to maintain responsiveness
      if (makingLargeMove) {
        // Run max 5 steps per loop cycle
        for (int i = 0; i < 5; i++) {
          if (stepper1.isRunning()) {
            stepper1.run();
          }
          if (stepper2.isRunning()) {
            stepper2.run();
          }
        }
      } else {
        // For normal moves, run normally
        stepper1.run();
        stepper2.run();
      }
      
      lastActivityTime = currentTime;  // Update activity timer while moving
    } else {
      // No longer moving
      makingLargeMove = false;
    }
  }
  
  // Check for inactivity timeout
  if (motorsEnabled && (currentTime - lastActivityTime > INACTIVITY_TIMEOUT)) {
    Serial.println("Motors disabled due to inactivity");
    disableMotors();
  }
  
  // Periodic status update in serial mode
  if (currentMode == MODE_SERIAL && (currentTime - lastStatusTime > STATUS_INTERVAL)) {
    sendStatusUpdate(CMD_STATUS);
    lastStatusTime = currentTime;
  }
  
  // Very short delay for stability
  delay(1);
}

void processCommand() {
  // Format: command_id, motor_select, param1, param2
  // Read first byte - command ID
  uint8_t cmd = myTransfer.packet.rxBuff[0];
  
  // Read second byte - motor select
  uint8_t motorSelect = myTransfer.packet.rxBuff[1];
  
  // Read param1 (4 bytes)
  int32_t param1;
  memcpy(&param1, &myTransfer.packet.rxBuff[2], sizeof(param1));
  
  // Read param2 (4 bytes)
  int32_t param2;
  memcpy(&param2, &myTransfer.packet.rxBuff[6], sizeof(param2));
  
  // Debug output
  Serial.print("Command: ");
  Serial.print(cmd);
  Serial.print(", Motor: ");
  Serial.print(motorSelect);
  Serial.print(", Param1: ");
  Serial.print(param1);
  Serial.print(", Param2: ");
  Serial.println(param2);
  
  // Process command
  switch (cmd) {
    case CMD_PING:
      sendPingResponse(param1);
      break;
      
    case CMD_MOVE:
      currentMode = MODE_SERIAL;
      enableMotors();  // Ensure motors are enabled before moving
      
      // Check if this is a large move
      if ((motorSelect & 1) && abs(param1) > LARGE_MOVE_THRESHOLD) {
        makingLargeMove = true;
      }
      if ((motorSelect & 2) && abs(param2) > LARGE_MOVE_THRESHOLD) {
        makingLargeMove = true;
      }
      
      if (motorSelect & 1) { // X axis
        stepper1.move(param1);
      }
      if (motorSelect & 2) { // Y axis
        stepper2.move(param2);
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_MOVETO:
      currentMode = MODE_SERIAL;
      enableMotors();  // Ensure motors are enabled before moving
      
      // Check if this is a large move
      if ((motorSelect & 1) && abs(param1 - stepper1.currentPosition()) > LARGE_MOVE_THRESHOLD) {
        makingLargeMove = true;
      }
      if ((motorSelect & 2) && abs(param2 - stepper2.currentPosition()) > LARGE_MOVE_THRESHOLD) {
        makingLargeMove = true;
      }
      
      if (motorSelect & 1) { // X axis
        stepper1.moveTo(param1);
      }
      if (motorSelect & 2) { // Y axis
        stepper2.moveTo(param2);
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_SPEED:
      if (motorSelect & 1) { // X axis
        stepper1.setMaxSpeed(param1);
      }
      if (motorSelect & 2) { // Y axis
        stepper2.setMaxSpeed(param2);
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_ACCEL:
      if (motorSelect & 1) { // X axis
        stepper1.setAcceleration(param1);
      }
      if (motorSelect & 2) { // Y axis
        stepper2.setAcceleration(param2);
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_HOME:
      currentMode = MODE_SERIAL;
      
      if (motorSelect & 1) { // X axis
        stepper1.setCurrentPosition(0);
      }
      if (motorSelect & 2) { // Y axis
        stepper2.setCurrentPosition(0);
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_STOP:
      if (motorSelect & 1) { // X axis
        stepper1.stop();
      }
      if (motorSelect & 2) { // Y axis
        stepper2.stop();
      }
      
      makingLargeMove = false;
      sendOkResponse(cmd);
      break;
      
    case CMD_MODE:
      if (param1 == MODE_JOYSTICK || param1 == MODE_SERIAL) {
        currentMode = param1;
        
        if (currentMode == MODE_JOYSTICK) {
          stepper1.stop();
          stepper2.stop();
          // Reset joystick-related variables
          motor1Speed = 0;
          motor2Speed = 0;
          makingLargeMove = false;
        }
        
        sendOkResponse(cmd);
      } else {
        sendErrorResponse(cmd, 1); // Invalid mode
      }
      break;
      
    case CMD_STATUS:
      sendStatusUpdate(cmd);
      break;
      
    case CMD_DISABLE:
      if (motorSelect & 1) { // X axis
        stepper1.disableOutputs();
      }
      if (motorSelect & 2) { // Y axis
        stepper2.disableOutputs();
      }
      
      if (motorSelect == 3) { // Both
        motorsEnabled = false;
      }
      
      sendOkResponse(cmd);
      break;
      
    case CMD_ENABLE:
      if (motorSelect & 1) { // X axis
        stepper1.enableOutputs();
      }
      if (motorSelect & 2) { // Y axis
        stepper2.enableOutputs();
      }
      
      if (motorSelect == 3) { // Both
        motorsEnabled = true;
      }
      
      sendOkResponse(cmd);
      break;
      
    default:
      sendErrorResponse(cmd, 2); // Unknown command
      break;
  }
}

void sendPingResponse(int32_t value) {
  // First byte is response ID
  myTransfer.packet.txBuff[0] = RESP_PING;
  
  // Next 4 bytes are the echo value
  memcpy(&myTransfer.packet.txBuff[1], &value, sizeof(value));
  
  // Send 5 bytes total
  myTransfer.sendData(5);
  
  Serial.print("Sent ping response with value: ");
  Serial.println(value);
}

void sendOkResponse(uint8_t cmd) {
  // First byte is response ID
  myTransfer.packet.txBuff[0] = RESP_OK;
  
  // Next byte is the command echo
  myTransfer.packet.txBuff[1] = cmd;
  
  // Next 4 bytes are X position
  int32_t xPos = stepper1.currentPosition();
  memcpy(&myTransfer.packet.txBuff[2], &xPos, sizeof(xPos));
  
  // Next 4 bytes are Y position
  int32_t yPos = stepper2.currentPosition();
  memcpy(&myTransfer.packet.txBuff[6], &yPos, sizeof(yPos));
  
  // Next 2 bytes are X speed
  int16_t xSpeed = stepper1.speed();
  memcpy(&myTransfer.packet.txBuff[10], &xSpeed, sizeof(xSpeed));
  
  // Next 2 bytes are Y speed
  int16_t ySpeed = stepper2.speed();
  memcpy(&myTransfer.packet.txBuff[12], &ySpeed, sizeof(ySpeed));
  
  // Next byte is X running
  myTransfer.packet.txBuff[14] = stepper1.isRunning() ? 1 : 0;
  
  // Next byte is Y running
  myTransfer.packet.txBuff[15] = stepper2.isRunning() ? 1 : 0;
  
  // Next byte is mode
  myTransfer.packet.txBuff[16] = currentMode;
  
  // Next 2 bytes are sequence
  uint16_t seq = sequenceCounter++;
  memcpy(&myTransfer.packet.txBuff[17], &seq, sizeof(seq));
  
  // Next 4 bytes are param1 (not used for OK response)
  int32_t param1 = 0;
  memcpy(&myTransfer.packet.txBuff[19], &param1, sizeof(param1));
  
  // Send 23 bytes total
  myTransfer.sendData(23);
  
  Serial.println("Sent OK response");
}

void sendErrorResponse(uint8_t cmd, uint8_t errorCode) {
  // First byte is response ID
  myTransfer.packet.txBuff[0] = RESP_ERROR;
  
  // Next byte is the command echo
  myTransfer.packet.txBuff[1] = cmd;
  
  // Next 4 bytes are X position
  int32_t xPos = stepper1.currentPosition();
  memcpy(&myTransfer.packet.txBuff[2], &xPos, sizeof(xPos));
  
  // Next 4 bytes are Y position
  int32_t yPos = stepper2.currentPosition();
  memcpy(&myTransfer.packet.txBuff[6], &yPos, sizeof(yPos));
  
  // Next 2 bytes are X speed
  int16_t xSpeed = stepper1.speed();
  memcpy(&myTransfer.packet.txBuff[10], &xSpeed, sizeof(xSpeed));
  
  // Next 2 bytes are Y speed
  int16_t ySpeed = stepper2.speed();
  memcpy(&myTransfer.packet.txBuff[12], &ySpeed, sizeof(ySpeed));
  
  // Next byte is X running
  myTransfer.packet.txBuff[14] = stepper1.isRunning() ? 1 : 0;
  
  // Next byte is Y running
  myTransfer.packet.txBuff[15] = stepper2.isRunning() ? 1 : 0;
  
  // Next byte is mode
  myTransfer.packet.txBuff[16] = currentMode;
  
  // Next 2 bytes are sequence
  uint16_t seq = sequenceCounter++;
  memcpy(&myTransfer.packet.txBuff[17], &seq, sizeof(seq));
  
  // Next 4 bytes are param1 (error code for error response)
  int32_t param1 = errorCode;
  memcpy(&myTransfer.packet.txBuff[19], &param1, sizeof(param1));
  
  // Send 23 bytes total
  myTransfer.sendData(23);
  
  Serial.print("Sent ERROR response with code: ");
  Serial.println(errorCode);
}

void sendStatusUpdate(uint8_t cmd) {
  // First byte is response ID
  myTransfer.packet.txBuff[0] = RESP_STATUS;
  
  // Next byte is the command echo
  myTransfer.packet.txBuff[1] = cmd;
  
  // Next 4 bytes are X position
  int32_t xPos = stepper1.currentPosition();
  memcpy(&myTransfer.packet.txBuff[2], &xPos, sizeof(xPos));
  
  // Next 4 bytes are Y position
  int32_t yPos = stepper2.currentPosition();
  memcpy(&myTransfer.packet.txBuff[6], &yPos, sizeof(yPos));
  
  // Next 2 bytes are X speed
  int16_t xSpeed = stepper1.speed();
  memcpy(&myTransfer.packet.txBuff[10], &xSpeed, sizeof(xSpeed));
  
  // Next 2 bytes are Y speed
  int16_t ySpeed = stepper2.speed();
  memcpy(&myTransfer.packet.txBuff[12], &ySpeed, sizeof(ySpeed));
  
  // Next byte is X running
  myTransfer.packet.txBuff[14] = stepper1.isRunning() ? 1 : 0;
  
  // Next byte is Y running
  myTransfer.packet.txBuff[15] = stepper2.isRunning() ? 1 : 0;
  
  // Next byte is mode
  myTransfer.packet.txBuff[16] = currentMode;
  
  // Next 2 bytes are sequence
  uint16_t seq = sequenceCounter++;
  memcpy(&myTransfer.packet.txBuff[17], &seq, sizeof(seq));
  
  // Next 4 bytes are param1 (not used for status)
  int32_t param1 = 0;
  memcpy(&myTransfer.packet.txBuff[19], &param1, sizeof(param1));
  
  // Send 23 bytes total
  myTransfer.sendData(23);
}

void enableMotors() {
  stepper1.enableOutputs();
  stepper2.enableOutputs();
  motorsEnabled = true;
  Serial.println("Motors enabled");
}

void disableMotors() {
  stepper1.disableOutputs();
  stepper2.disableOutputs();
  motorsEnabled = false;
  Serial.println("Motors disabled");
}

// Returns true if joystick is active
bool handleJoystick() {
  // Read joystick
  int joyX = analogRead(JOY_X_PIN);
  int joyY = analogRead(JOY_Y_PIN);
  int joySW = digitalRead(JOY_SW_PIN);
  
  // Calculate X motor speed
  int prevMotor1Speed = motor1Speed;
  if (abs(joyX - JOY_CENTER) > DEADZONE) {
    int xOffset = joyX - JOY_CENTER;
    motor1Speed = map(abs(xOffset), DEADZONE, 512 - DEADZONE, minSpeed, maxSpeed);
    motor1Speed = xOffset > 0 ? motor1Speed : -motor1Speed;
  } else {
    motor1Speed = 0;
  }
  
  // Calculate Y motor speed
  int prevMotor2Speed = motor2Speed;
  if (abs(joyY - JOY_CENTER) > DEADZONE) {
    int yOffset = joyY - JOY_CENTER;
    motor2Speed = map(abs(yOffset), DEADZONE, 512 - DEADZONE, minSpeed, maxSpeed);
    motor2Speed = yOffset > 0 ? motor2Speed : -motor2Speed;
  } else {
    motor2Speed = 0;
  }
  
  // Check if joystick is active
  bool joystickActive = (motor1Speed != 0 || motor2Speed != 0 || 
                          motor1Speed != prevMotor1Speed || motor2Speed != prevMotor2Speed);
  
  // Run motors if there's movement
  if (motor1Speed != 0) {
    if (!motorsEnabled) {
      enableMotors();
    }
    stepper1.setSpeed(motor1Speed);
    stepper1.runSpeed();
  }
  
  if (motor2Speed != 0) {
    if (!motorsEnabled) {
      enableMotors();
    }
    stepper2.setSpeed(motor2Speed);
    stepper2.runSpeed();
  }
  
  // Toggle motors on button press
  static bool lastJoySW = HIGH;
  if (joySW != lastJoySW && joySW == LOW) {
    if (motorsEnabled) {
      disableMotors();
    } else {
      enableMotors();
    }
    
    joystickActive = true;  // Button press counts as joystick activity
  }
  lastJoySW = joySW;
  
  return joystickActive;
}