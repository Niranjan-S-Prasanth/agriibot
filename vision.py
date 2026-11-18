import cv2
import serial
import time

# Update COM port to match your hardware connection
arduino = serial.Serial('COM3', 115200)
time.sleep(2)

cap = cv2.VideoCapture(0)

def analyze_plant_health(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Color ranges for green vs stressed foliage
    lower_green = (35, 40, 40)
    upper_green = (85, 255, 255)
    lower_stress = (15, 40, 40)
    upper_stress = (35, 255, 255)

    green_pixels = cv2.countNonZero(cv2.inRange(hsv, lower_green, upper_green))
    stress_pixels = cv2.countNonZero(cv2.inRange(hsv, lower_stress, upper_stress))

    return green_pixels, stress_pixels

last_sent = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.resize(frame, (640, 480))
    green_count, stress_count = analyze_plant_health(frame)
    current_time = time.time()

    if stress_count > 5000 and stress_count > green_count:
        cv2.putText(frame, "STATUS: PLANT STRESS (Spraying Neem)", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        if current_time - last_sent > 5:
            arduino.write(b'P') # Sends 'P' to trigger Neem pump
            last_sent = current_time
    else:
        cv2.putText(frame, "STATUS: Crops Healthy", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("Agrobot Vision Stream", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()