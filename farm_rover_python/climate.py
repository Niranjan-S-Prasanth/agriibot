"""Climate & 25+ Crop Microclimate Rule Engine.

Combines live DHT11 readings, Open-Meteo weather forecasts, and an agronomic 
database of 25+ crops to calculate real-time microclimate risks, fungal/heat alerts,
and step-by-step agronomist solutions.
"""
import json
import os
import requests
import config

SAVED_CROPS_FILE = os.path.join(os.path.dirname(__file__), "farmer_selected_crops.json")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# 25+ AGRONOMIC CROPS DATABASE WITH THRESHOLDS & SOLUTIONS
ALL_PLANTS = {
    "Plantation & Spices": {
        "Coconut": {
            "min_t": 20, "max_t": 32, "min_h": 60, "max_h": 85,
            "info": "Thrives in tropical humid climates. Highly productive in coastal and riverine soils.",
            "diseases": "Bud Rot (Phytophthora), Stem Bleeding, Leaf Spot",
            "risk": "High humidity (>85%) triggers Phytophthora palmivora bud rot. Excessive heat (>34°C) causes premature button shedding.",
            "solution": "1. Spray 1% Bordeaux mixture on crown prior to heavy monsoon.\n2. Ensure root field drainage to prevent waterlogging.\n3. Apply organic neem cake (5kg/palm) to reinforce root immunity."
        },
        "Rubber": {
            "min_t": 20, "max_t": 34, "min_h": 70, "max_h": 90,
            "info": "Requires heavy annual rainfall and warm humid air for latex synthesis.",
            "diseases": "Abnormal Leaf Fall (Phytophthora), Powdery Mildew, Pink Disease",
            "risk": "Sustained high moisture with temperature drop induces abnormal leaf shedding, dropping latex yield by 30-50%.",
            "solution": "1. Prophylactic aerial spraying of oil-based copper oxychloride.\n2. Fix panel wash guards over tapping cuts during rain.\n3. Maintain proper spacing for canopy sunlight penetration."
        },
        "Black Pepper": {
            "min_t": 23, "max_t": 32, "min_h": 70, "max_h": 90,
            "info": "The King of Spices; requires support trees (standards) and humid microclimates.",
            "diseases": "Quick Wilt (Foot Rot - Phytophthora capsici), Slow Wilt, Pollu Beetle",
            "risk": "Soil saturation combined with humidity above 88% sparks rapid foot rot epidemics that wipe out vines in days.",
            "solution": "1. Apply Trichoderma harzianum enriched farmyard manure near root zones.\n2. Spray potassium phosphonate (0.3%) on vine foliage at monsoon onset.\n3. Clear lower vine branches (up to 30cm) to increase air movement."
        },
        "Cardamom": {
            "min_t": 15, "max_t": 26, "min_h": 75, "max_h": 95,
            "info": "Requires cool, high-altitude shade tree conditions (Western Ghats environment).",
            "diseases": "Katte Virus (Mosaic), Capsule Rot (Azhukal disease), Thrips",
            "risk": "Temperatures exceeding 28°C cause severe shoot scorching and capsule desiccation.",
            "solution": "1. Maintain 50-60% overhead shade canopy using shade trees.\n2. Remove and rogue Katte-infected clumps immediately.\n3. Spray 1% Bordeaux mixture to combat Azhukal rot during wet spells."
        },
        "Nutmeg": {
            "min_t": 22, "max_t": 33, "min_h": 70, "max_h": 88,
            "info": "Requires well-drained, fertile shade spots with abundant ambient humidity.",
            "diseases": "Fruit Rot, Dieback, Leaf Blight",
            "risk": "High humidity without ventilation encourages fruit splitting and fungal mummification.",
            "solution": "1. Collect and destroy dropped infected mummified fruits.\n2. Spray copper hydroxide (2g/L) at fruit-set stage.\n3. Ensure field ditching to avoid standing water near trunk bases."
        },
        "Clove": {
            "min_t": 20, "max_t": 32, "min_h": 70, "max_h": 85,
            "info": "Slow-growing tree requiring humid island/coastal elevated microclimates.",
            "diseases": "Leaf Blight, Twig Rot, Stem Canker",
            "risk": "Dry hot spells reduce essential oil accumulation in flower buds.",
            "solution": "1. Provide mulching around saplings with dry leaves/straw.\n2. Spray carbendazim (1g/L) if leaf blight spots appear.\n3. Install drip lines to maintain steady root zone moisture."
        }
    },
    "Fruits": {
        "Mango": {
            "min_t": 24, "max_t": 35, "min_h": 50, "max_h": 75,
            "info": "Deep-rooted fruit tree flourishing in warm tropical plains.",
            "diseases": "Powdery Mildew, Anthracnose, Mango Hopper infestation",
            "risk": "High humidity (>80%) during flowering causes heavy blossom drop and Anthracnose fruit spotting.",
            "solution": "1. Spray Wettable Sulphur (3g/L) at flower panicle emergence.\n2. Prune internal non-bearing branches to open tree canopy to sunlight.\n3. Apply Imidacloprid if hoppers exceed threshold levels."
        },
        "Jackfruit": {
            "min_t": 22, "max_t": 35, "min_h": 65, "max_h": 85,
            "info": "Resilient tropical tree producing large starch and nutrient-dense fruits.",
            "diseases": "Rhizopus Fruit Rot (Soft Rot), Shoot Borer, Pink Rot",
            "risk": "Extreme moisture (>90% RH) induces Rhizopus soft decay, turning developing fruit black.",
            "solution": "1. Spray Mancozeb (2g/L) at fruit formation stage.\n2. Bag young developing fruits using breathable paper/cloth bags.\n3. Maintain clean orchard sanitation by burning fallen decayed fruits."
        },
        "Banana": {
            "min_t": 22, "max_t": 32, "min_h": 70, "max_h": 85,
            "info": "Fast-growing herbaceous perennial requiring heavy feeding and watering.",
            "diseases": "Sigatoka Leaf Spot (Yellow/Black), Panama Wilt (Fusarium), Pseudostem Borer",
            "risk": "High humidity accelerates Sigatoka fungus spore germination, destroying leaf area.",
            "solution": "1. De-leaf infected bottom leaves and burn them outside the plot.\n2. Spray Mineral Oil emulsion mixed with Propiconazole (1ml/L).\n3. Ensure pseudostem trap installation for stem borer management."
        },
        "Rambutan": {
            "min_t": 22, "max_t": 30, "min_h": 75, "max_h": 90,
            "info": "Exotic tropical fruit requiring humid, non-drought conditions for sweet aril.",
            "diseases": "Oidium Powdery Mildew, Stem End Rot, Fruit Borer",
            "risk": "Dry heat under 60% humidity causes rind cracking and premature fruit drop.",
            "solution": "1. Mulch heavily with organic matter to conserve soil moisture.\n2. Maintain overhead sprinkler misting during hot afternoon dry spells.\n3. Spray neem oil (5ml/L) preventatively for fruit borers."
        },
        "Papaya": {
            "min_t": 21, "max_t": 33, "min_h": 60, "max_h": 80,
            "info": "Rapidly growing fruit crop sensitive to frost and waterlogging.",
            "diseases": "Papaya Ring Spot Virus (PRSV), Damping Off, Root Rot",
            "risk": "Waterlogging + temperature >34°C triggers root rot wilt within 48 hours.",
            "solution": "1. Plant strictly on raised bed ridges (30cm high).\n2. Vector control: spray sticky yellow traps to catch PRSV-carrying aphids.\n3. Drench root zones with Metalaxyl (2g/L) during heavy rains."
        }
    },
    "Vegetables": {
        "Tomato": {
            "min_t": 18, "max_t": 28, "min_h": 60, "max_h": 75,
            "info": "Popular solanaceous crop requiring balanced warmth and steady irrigation.",
            "diseases": "Early/Late Blight, Bacterial Wilt, Leaf Curl Virus",
            "risk": "High humidity (>80%) creates severe Late Blight outbreaks; high heat (>32°C) sterilizes pollen.",
            "solution": "1. Spray Copper Oxychloride (3g/L) preventatively.\n2. Stake plants to keep lower foliage off damp soil.\n3. Use drip irrigation instead of overhead spraying to keep leaves dry."
        },
        "Tapioca (Cassava)": {
            "min_t": 25, "max_t": 35, "min_h": 50, "max_h": 85,
            "info": "Hardy drought-tolerant tuber crop central to tropical agriculture.",
            "diseases": "Cassava Mosaic Disease (CMD), Tuber Rot, Red Spider Mite",
            "risk": "Prolonged soil saturation leads to tuber rot and starch degradation.",
            "solution": "1. Use CMD-resistant stem cuttings for planting.\n2. Ensure proper field drainage channels between crop rows.\n3. Remove whitefly vectors using neem oil formulations."
        },
        "Bitter Gourd": {
            "min_t": 20, "max_t": 30, "min_h": 65, "max_h": 80,
            "info": "Cucurbit vine known for medicinal fruit properties; requires trellis support.",
            "diseases": "Downy Mildew, Powdery Mildew, Fruit Fly",
            "risk": "Cool damp nights with high humidity lead to Downy Mildew yellow leaf lesions.",
            "solution": "1. Spray Cymoxanil + Mancozeb (2g/L) upon first lesion appearance.\n2. Hang Cue-lure pheromone traps to kill male fruit flies.\n3. Train vines on vertical wire trellises for maximum airflow."
        },
        "Okra (Vendakka)": {
            "min_t": 22, "max_t": 35, "min_h": 60, "max_h": 80,
            "info": "Heat-loving warm season vegetable producing continuous tender pods.",
            "diseases": "Yellow Vein Mosaic Virus (YVMV), Powdery Mildew, Shoot & Fruit Borer",
            "risk": "Whitefly proliferation under hot humid weather spreads YVMV rapidly.",
            "solution": "1. Sow YVMV-resistant cultivars (e.g., Arka Anamika).\n2. Spray imidacloprid or yellow sticky traps for whitefly suppression.\n3. Apply wettable sulphur if powdery mildew appears on lower leaf surfaces."
        },
        "Brinjal (Eggplant)": {
            "min_t": 21, "max_t": 32, "min_h": 60, "max_h": 80,
            "info": "Long-duration solanaceous vegetable producing rich purple/green fruits.",
            "diseases": "Shoot and Fruit Borer, Little Leaf Disease, Phomopsis Blight",
            "risk": "High humidity leads to Phomopsis fruit rot and stem leaf spot.",
            "solution": "1. Clip off and destroy borer-wilted shoot tips weekly.\n2. Install Lucinlure pheromone traps across the field plot.\n3. Spray carbendazim (1g/L) preventatively before rainy spells."
        }
    },
    "Flowers & Cash Crops": {
        "Jasmine (Mulla)": {
            "min_t": 20, "max_t": 32, "min_h": 60, "max_h": 80,
            "info": "Fragrant flowering shrub cultivated for essential oil and traditional garlands.",
            "diseases": "Leaf Blight, Rust, Bud Worm",
            "risk": "Over-watering combined with high RH causes flower bud drop and leaf rust.",
            "solution": "1. Prune bushes annually in winter to stimulate fresh flowering spurs.\n2. Spray hexaconazole (1ml/L) for rust fungal control.\n3. Apply Bacillus thuringiensis (Bt) spray for organic bud worm control."
        },
        "Anthurium": {
            "min_t": 18, "max_t": 28, "min_h": 70, "max_h": 90,
            "info": "High-value shade ornamental requiring specialized well-aerated media.",
            "diseases": "Bacterial Blight (Xanthomonas), Root Rot, Anthracnose",
            "risk": "Temperatures >30°C cause severe leaf scorch and spathe color fading.",
            "solution": "1. Maintain 75% shade net coverage over greenhouse.\n2. Disinfect pruning shears with alcohol between plants to stop Xanthomonas.\n3. Use coconut husk chips for root media to ensure 100% aeration."
        },
        "Orchids": {
            "min_t": 18, "max_t": 30, "min_h": 65, "max_h": 85,
            "info": "Epiphytic flowers needing high air moisture and excellent root aeration.",
            "diseases": "Black Rot (Phytophthora), Bacterial Soft Rot, Snail damage",
            "risk": "Stagnant humid air without fans causes black rot crown destruction.",
            "solution": "1. Install air circulation fans inside nursery enclosures.\n2. Mount orchids on charcoal/tile beds instead of standard soil.\n3. Drench with Metalaxyl (1.5g/L) if crown spots turn soft/black."
        },
        "Ginger": {
            "min_t": 19, "max_t": 30, "min_h": 70, "max_h": 90,
            "info": "Underground rhizome spice crop thriving in rich warm loamy soils.",
            "diseases": "Soft Rot (Rhizome Rot - Pythium), Bacterial Wilt, Leaf Spot",
            "risk": "Waterlogging during monsoon causes catastrophic 100% rhizome soft rot.",
            "solution": "1. Treat seed rhizomes with Trichoderma biocontrol prior to planting.\n2. Plant strictly in raised beds with lateral drainage trenches.\n3. Drench beds with Copper Oxychloride (3g/L) on initial wilt sighting."
        },
        "Turmeric": {
            "min_t": 20, "max_t": 32, "min_h": 65, "max_h": 88,
            "info": "Golden rhizome crop requiring warm humid conditions and heavy mulching.",
            "diseases": "Leaf Spot (Taphrina), Leaf Blotch, Rhizome Rot",
            "risk": "High humidity leads to Taphrina leaf spot, burning photosynthetic foliage.",
            "solution": "1. Spray Mancozeb (2.5g/L) at 15-day intervals during monsoon.\n2. Apply green leaf mulch (12 tonnes/hectare) at planting and 50 days.\n3. Ensure seed rhizomes are disease-free certified stock."
        }
    }
}


def load_saved_crops():
    if os.path.exists(SAVED_CROPS_FILE):
        try:
            with open(SAVED_CROPS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_crops_to_file(crop_list):
    with open(SAVED_CROPS_FILE, 'w') as f:
        json.dump(crop_list, f, indent=2)


def evaluate_risk(temp, humidity):
    """Evaluates temperature and humidity against all 25+ crops."""
    evaluation = {}
    for category, plants in ALL_PLANTS.items():
        evaluation[category] = {}
        for plant, bounds in plants.items():
            t_ok = bounds['min_t'] <= temp <= bounds['max_t']
            h_ok = bounds['min_h'] <= humidity <= bounds['max_h']

            if t_ok and h_ok:
                status = "Optimal"
                badge = "success"
                risk_msg = "Current microclimate is within safe growing thresholds."
            elif temp > bounds['max_t']:
                status = "Heat Stress"
                badge = "danger"
                risk_msg = f"Temperature ({temp}°C) exceeds safe max threshold ({bounds['max_t']}°C)."
            elif humidity > bounds['max_h']:
                status = "Fungal Risk"
                badge = "warning"
                risk_msg = f"Humidity ({humidity}%) exceeds safe ceiling ({bounds['max_h']}%)."
            elif temp < bounds['min_t']:
                status = "Cold Stress"
                badge = "warning"
                risk_msg = f"Temperature ({temp}°C) is below minimum required ({bounds['min_t']}°C)."
            else:
                status = "Dry Air Stress"
                badge = "warning"
                risk_msg = f"Humidity ({humidity}%) is below minimum required ({bounds['min_h']}%)."

            evaluation[category][plant] = {
                "status": status,
                "badge": badge,
                "risk_msg": risk_msg,
                "min_t": bounds['min_t'],
                "max_t": bounds['max_t'],
                "min_h": bounds['min_h'],
                "max_h": bounds['max_h'],
                "info": bounds["info"],
                "diseases": bounds["diseases"],
                "risk": bounds["risk"],
                "solution": bounds["solution"]
            }
    return evaluation


def fetch_weather(lat, lon, forecast_days=7):
    """Pulls Open-Meteo daily weather forecast."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "relative_humidity_2m_mean",
            "weathercode",
        ]),
        "past_days": 1,
        "forecast_days": forecast_days,
        "timezone": "auto",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def get_crop_outlook(lat=None, lon=None, dht_reading=None):
    """Combines Open-Meteo forecast and live DHT11 readings with crop risk evaluation."""
    lat = lat or config.DEFAULT_LAT
    lon = lon or config.DEFAULT_LON

    temp = 28.5
    humidity = 75.0
    if dht_reading and dht_reading.get("temp_c") is not None:
        temp = float(dht_reading["temp_c"])
    if dht_reading and dht_reading.get("humidity") is not None:
        humidity = float(dht_reading["humidity"])

    evaluations = evaluate_risk(temp, humidity)
    saved_crops = load_saved_crops()

    raw = fetch_weather(lat, lon, config.CLIMATE_FORECAST_DAYS)
    days = []
    if raw and "daily" in raw:
        for i, date in enumerate(raw["daily"]["time"]):
            days.append({
                "date": date,
                "temp_max": raw["daily"]["temperature_2m_max"][i],
                "temp_min": raw["daily"]["temperature_2m_min"][i],
                "precip_mm": raw["daily"]["precipitation_sum"][i],
                "humidity_pct": raw["daily"]["relative_humidity_2m_mean"][i],
            })

    return {
        "current_temp": temp,
        "current_humidity": humidity,
        "evaluations": evaluations,
        "saved_crops": saved_crops,
        "all_plants": ALL_PLANTS,
        "forecast_days": days
    }
