# Agronomic Telemetry & Microclimate Risk Engine (Flask REST API)

A standalone Python Flask REST API that provides real-time microclimate risk analysis, crop evaluation, and simulation capabilities. The engine processes temperature and humidity sensor inputs against an extensive agronomic database to evaluate crop health thresholds, disease threats, and mitigation strategies.

---

## 🛠️ Features

- **Decoupled REST API Architecture:** Works as a headless backend service for IoT devices (ESP32, Arduino), CLI tools, or mobile clients.
- **Microclimate Simulation Engine:** Dynamically switch between live DHT sensor baselines and simulated custom temperature/humidity test states.
- **Comprehensive Agronomic Database:** Built-in thresholds, disease risk vectors, and treatment procedures for 20+ tropical, spice, and cash crops.
- **Persisted Farmer Preferences:** JSON-backed persistence for saving active crop filters across application restarts.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- `pip` package manager

### Installation

1. **Clone or download the repository:**
   ```bash
   git clone <repository-url>
   cd <repository-folder>