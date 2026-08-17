"""Hack Club Qwen-32B AI Agronomist Assistant.

Uses https://ai.hackclub.com/proxy/v1/chat/completions (qwen/qwen3-32b) to provide
real-time agronomic advice, telemetry analysis, and custom disease remedy summaries.
"""
import requests
import config

def call_qwen_ai(messages, timeout=12):
    """Sends messages list to Hack Club Qwen-32B AI API. Returns string response or None."""
    headers = {
        "Authorization": f"Bearer {config.HACKCLUB_AI_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": config.HACKCLUB_AI_MODEL,
        "messages": messages
    }
    try:
        resp = requests.post(config.HACKCLUB_AI_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            return content.strip()
    except Exception as e:
        print(f"Warning: Hack Club AI API call failed: {e}")
    return None


def generate_disease_ai_summary(label, confidence, description, steps, supplement):
    """Uses Qwen 32B to generate a tailored executive summary for detected disease."""
    prompt = f"""You are an expert AI Agronomist assisting a farmer.
A laptop camera scan detected:
- Crop / Disease: {label} (Confidence: {confidence}%)
- Raw Description: {description}
- Default Remedy Steps: {steps}
- Recommended Supplement: {supplement}

Please provide a clear, 3-paragraph executive report:
1. Executive Summary: What this condition means for the crop.
2. Immediate Action Plan: 3 step-by-step instructions for the farmer.
3. Long-term Prevention & Supplement Advice: How to prevent recurrence using {supplement} or organic practices.
Keep the tone helpful, professional, and easy to read.
"""
    messages = [
        {"role": "system", "content": "You are a professional AI Agronomist specializing in plant pathology and precision agriculture."},
        {"role": "user", "content": prompt}
    ]

    res = call_qwen_ai(messages, timeout=10)
    return res


def answer_farmer_question(question, state_snapshot=None):
    """Answers farmer Q&A using Qwen-32B model, incorporating live telemetry context."""
    telemetry_ctx = ""
    if state_snapshot:
        dht = state_snapshot.get("dht", {})
        soil = state_snapshot.get("soil", {})
        gps = state_snapshot.get("gps", {})
        last_d = state_snapshot.get("last_disease")

        p_logs = state_snapshot.get("pump_logs", [])
        s_logs = state_snapshot.get("sensor_logs", [])

        pump_summary = "No irrigation events recorded yet."
        if p_logs:
            pump_summary = "\n".join([
                f"  • [{p.get('time_str')}] Zone {p.get('side')}: Pumped for {p.get('duration_sec')}s (Deficit {p.get('deficit_pct')}%, Trigger: {p.get('trigger')})"
                for p in p_logs[:5]
            ])

        sensor_summary = "No historic sensor trends logged yet."
        if s_logs:
            sensor_summary = "\n".join([
                f"  • [{s.get('time_str')}] Temp={s.get('temp')}°C, Humid={s.get('humidity')}%, Soil(L/C/R)={s.get('soil_L')}%/{s.get('soil_C')}%/{s.get('soil_R')}%"
                for s in s_logs[:5]
            ])

        telemetry_ctx = f"""
LIVE ROVER TELEMETRY CONTEXT:
- Air Temp: {dht.get('temp_c', 28.5)}°C | Humidity: {dht.get('humidity', 75.0)}%
- Soil Moisture Zones: Left={soil.get('L', {}).get('pct', '68')}%, Center={soil.get('C', {}).get('pct', '62')}%, Right={soil.get('R', {}).get('pct', '54')}%
- Obstacle Distance: {state_snapshot.get('obstacle_cm', 120)} cm
- GPS Coordinates: Lat {gps.get('lat', 10.7628)}, Lon {gps.get('lon', 76.6548)}
- Driving Status: {state_snapshot.get('status', 'SYSTEM READY')}
- Last Detected Plant Event: {last_d.get('label') if last_d else 'None'}

PUMPED WATER ACTIVITY LOGS:
{pump_summary}

SENSED ENVIRONMENTAL HISTORY LOGS:
{sensor_summary}
"""

    sys_msg = "You are a knowledgeable, friendly AI Agronomist and Farm Rover Assistant. Answer the farmer's question clearly and concisely."
    if telemetry_ctx:
        sys_msg += "\nUse the following live sensor context if relevant to the user's question:\n" + telemetry_ctx

    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": question}
    ]

    res = call_qwen_ai(messages, timeout=6)
    if res:
        return res

    # Rule-based fallback if cloud API is slow or offline
    dht_obj = state_snapshot.get("dht", {}) if state_snapshot else {}
    t_val = dht_obj.get("temp_c")
    h_val = dht_obj.get("humidity")
    dht_str = f"{t_val}°C and {h_val}% relative humidity" if t_val is not None and h_val is not None else "Sensor unplugged / Offline"

    p_logs = state_snapshot.get("pump_logs", []) if state_snapshot else []
    pump_str = "No recent water pumping activity."
    if p_logs:
        last_p = p_logs[0]
        pump_str = f"Last pumping recorded at {last_p.get('time_str')} on Zone {last_p.get('side')} for {last_p.get('duration_sec')}s (Trigger: {last_p.get('trigger')}). Total pump events logged: {len(p_logs)}."

    return (
        f"🌱 **Farm Rover Data Log & Agronomist Summary**:\n\n"
        f"1. **Ambient Microclimate**: {dht_str}.\n"
        f"2. **Pumping & Irrigation Activity**: {pump_str}\n"
        f"3. **Agronomist Insight for '{question}'**: Soil moisture targets should be maintained between 60% and 80%. Automatic irrigation triggers when soil deficit exceeds threshold."
    )

