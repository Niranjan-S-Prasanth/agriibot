"""Parses raw lines from Arduino Mega into structured events.

Recognized lines:
    SCAN,L,<raw>,C,<raw>,R,<raw>
    GPS,<lat>,<lon>,<speed>,<sat>,<hh:mm:ss>
    DHT,<tempC>,<humidity>
    OBSTACLE,<cm>
    ENCODER,<count>
    STATUS,<text>
"""

def parse_line(line: str):
    """Returns (event_type, data_dict) or (None, None) if unrecognized."""
    parts = line.split(",")
    tag = parts[0]

    if tag == "SCAN" and len(parts) >= 7:
        return "SCAN", {
            "L": int(parts[2]), "C": int(parts[4]), "R": int(parts[6])
        }

    if tag == "GPS" and len(parts) >= 6:
        return "GPS", {
            "lat": float(parts[1]), "lon": float(parts[2]),
            "speed_kmh": float(parts[3]), "sats": int(parts[4]),
            "time": parts[5],
        }

    if tag == "DHT" and len(parts) >= 3:
        try:
            temp = float(parts[1])
            hum = float(parts[2])
            import math
            if math.isnan(temp) or math.isnan(hum) or temp <= -40 or temp > 80 or hum < 0 or hum > 100:
                return "DHT", {
                    "temp_c": None, "humidity": None, "connected": False, "status": "INVALID_SIGNAL"
                }
            return "DHT", {
                "temp_c": temp, "humidity": hum, "connected": True, "status": "CONNECTED"
            }
        except (ValueError, TypeError):
            return "DHT", {
                "temp_c": None, "humidity": None, "connected": False, "status": "READ_ERROR"
            }

    if tag == "OBSTACLE" and len(parts) >= 2:
        return "OBSTACLE", {"cm": int(parts[1])}

    if tag == "ENCODER" and len(parts) >= 2:
        return "ENCODER", {"count": int(parts[1])}

    if tag == "STATUS" and len(parts) >= 2:
        return "STATUS", {"text": ",".join(parts[1:])}

    return None, None
