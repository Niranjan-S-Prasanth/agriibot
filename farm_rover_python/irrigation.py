"""Soil scan -> water-level -> proportional pump decision.

Doesn't just check "is there water or not" — it converts the raw
capacitive sensor reading into an actual moisture %, then into a water
LEVEL relative to a target:

    water_level = current_moisture_pct - MOISTURE_TARGET_PCT

    water_level >= 0   -> soil has enough, do nothing
    water_level <  0   -> soil is short by |water_level| percentage
                           points — that's the deficit the pump needs
                           to make up

The pump only runs long enough to cover that specific deficit (scaled by
WATER_SEC_PER_DEFICIT_PCT, clamped between MIN_PUMP_SEC and
MAX_PUMP_SEC) instead of a fixed blast every time — so a side that's
only a little dry gets a little water, and a side that's very dry gets
more, without ever exceeding the safety cap (no overloading / flooding).
"""
import time
import config


def raw_to_pct(raw):
    """Raw capacitive-sensor ADC value -> 0-100% moisture."""
    pct = (raw - config.AIR_VALUE) * 100 / (config.WATER_VALUE - config.AIR_VALUE)
    return max(0, min(100, pct))


def water_level(pct):
    """How far current moisture is from the target, signed.
    Negative = short by that many percentage points (needs water)."""
    return round(pct - config.MOISTURE_TARGET_PCT, 1)


def pump_duration_for_deficit(deficit_pct):
    """deficit_pct is the POSITIVE amount of moisture missing.
    Returns 0 if nothing is needed, otherwise a duration clamped to a
    safe range so the pump never overwaters."""
    if deficit_pct <= 0:
        return 0
    seconds = deficit_pct * config.WATER_SEC_PER_DEFICIT_PCT
    return max(config.MIN_PUMP_SEC, min(config.MAX_PUMP_SEC, seconds))


def decide_pumps(scan_data: dict):
    """scan_data = {'L':raw,'C':raw,'R':raw}. Returns per-side info:
        {"L": {"pct":.., "water_level":.., "duration_sec":..},
         "C": {"pct":.., "water_level":.., "duration_sec":None},  # no pump for center
         "R": {...}}
    duration_sec is 0 when that side doesn't need water, None where
    there's no pump for that position (center)."""
    result = {}
    for side in ("L", "C", "R"):
        pct = raw_to_pct(scan_data[side])
        level = water_level(pct)
        if side == "C":
            result[side] = {"pct": round(pct, 1), "water_level": level, "duration_sec": None}
            continue
        deficit = max(0, -level)
        duration = pump_duration_for_deficit(deficit)
        result[side] = {"pct": round(pct, 1), "water_level": level, "duration_sec": duration}
    return result


def _run_side(sender, side, duration_sec, logger, state=None, deficit_pct=0.0):
    logger.info(f"Irrigating {side} for {duration_sec:.1f}s (proportional to deficit)")
    sender.pump_on(side)
    if state and hasattr(state, "log_pump_event"):
        state.log_pump_event(side, duration_sec, trigger="AUTOMATIC_SOIL_DEFICIT", deficit_pct=deficit_pct)
    time.sleep(duration_sec)
    sender.pump_off(side)


def run_irrigation_cycle(sender, scan_data, logger, state=None):
    info = decide_pumps(scan_data)
    l, r = info["L"], info["R"]
    logger.info(
        f"Soil L: {l['pct']}% (level {l['water_level']:+.1f}) | "
        f"R: {r['pct']}% (level {r['water_level']:+.1f})"
    )

    if l["duration_sec"] == 0 and r["duration_sec"] == 0:
        logger.info("Both sides at/above target, no irrigation needed.")
        return

    if l["duration_sec"] > 0:
        _run_side(sender, "L", l["duration_sec"], logger, state=state, deficit_pct=max(0, -l["water_level"]))
    if r["duration_sec"] > 0:
        _run_side(sender, "R", r["duration_sec"], logger, state=state, deficit_pct=max(0, -r["water_level"]))
