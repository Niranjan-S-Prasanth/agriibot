import os
import csv
try:
    import pandas as pd
except ImportError:
    pd = None

import config
from ml_model import MLModel

class DiseaseDetector:
    def __init__(self):
        self.model = MLModel()
        self.disease_info = None
        self.supplement_info = None
        self._load_metadata()

    def _load_metadata(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_disease = os.path.join(base_dir, "disease_info.csv")
        plantdoc_disease = os.path.abspath(os.path.join(base_dir, "../PlantDoc/Model_assest/disease_info.csv"))
        disease_csv = local_disease if os.path.exists(local_disease) else plantdoc_disease

        local_supp = os.path.join(base_dir, "supplement_info.csv")
        plantdoc_supp = os.path.abspath(os.path.join(base_dir, "../PlantDoc/Model_assest/supplement_info.csv"))
        supp_csv = local_supp if os.path.exists(local_supp) else plantdoc_supp

        if os.path.exists(disease_csv):
            try:
                if pd is not None:
                    self.disease_info = pd.read_csv(disease_csv).to_dict(orient='records')
                else:
                    with open(disease_csv, mode='r', encoding='utf-8', errors='ignore') as f:
                        self.disease_info = list(csv.DictReader(f))
            except Exception as e:
                print(f"Warning: Could not read {disease_csv}: {e}")

        if os.path.exists(supp_csv):
            try:
                if pd is not None:
                    self.supplement_info = pd.read_csv(supp_csv, encoding='cp1252').to_dict(orient='records')
                else:
                    with open(supp_csv, mode='r', encoding='cp1252', errors='ignore') as f:
                        self.supplement_info = list(csv.DictReader(f))
            except Exception as e:
                print(f"Warning: Could not read {supp_csv}: {e}")

    def check(self, frame_bgr):
        """Returns (label, confidence, accepted: bool). Backward compatible signature."""
        if not self.is_plant_image(frame_bgr):
            return "No Plant / Leaf Detected", 0.0, False
        label, confidence, idx = self.model.predict(frame_bgr)
        accepted = confidence >= config.CONFIDENCE_THRESHOLD
        return label, confidence, accepted

    def is_plant_image(self, frame_bgr):
        """Checks if the frame contains a valid plant leaf or crop using HSV color distribution."""
        if frame_bgr is None or frame_bgr.size == 0:
            return False
        import cv2
        import numpy as np

        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

        # 1. Healthy green foliage (Hue 35 to 85, Sat > 30, Val > 30)
        green_mask = (h >= 35) & (h <= 85) & (s > 30) & (v > 30)
        green_ratio = float(np.count_nonzero(green_mask)) / float(frame_bgr.shape[0] * frame_bgr.shape[1])

        # 2. Diseased leaf yellow/brown (Hue 20 to 35, Sat > 45, Val > 40)
        yellow_mask = (h >= 20) & (h < 35) & (s > 45) & (v > 40)
        yellow_ratio = float(np.count_nonzero(yellow_mask)) / float(frame_bgr.shape[0] * frame_bgr.shape[1])

        # 3. Human skin tone / indoor wall range (Hue <= 18, Sat 20 to 160)
        skin_mask = (h <= 18) & (s >= 20) & (s <= 160) & (v >= 50) & (v <= 240)
        skin_ratio = float(np.count_nonzero(skin_mask)) / float(frame_bgr.shape[0] * frame_bgr.shape[1])

        total_plant_ratio = green_ratio + yellow_ratio

        # At least 3.5% plant pixels AND plant pixels must outweigh human skin pixels
        return (total_plant_ratio >= 0.035) and (total_plant_ratio > skin_ratio * 0.4)

    def diagnose(self, frame_bgr, generate_ai_summary=True, target_crop=None):
        """Returns a comprehensive dictionary with plant health status, description, remedies, supplements, and Qwen AI report."""
        if not self.is_plant_image(frame_bgr):
            return {
                "label": "No Plant / Leaf Detected",
                "confidence": 0.0,
                "confidence_ratio": 0.0,
                "accepted": False,
                "is_healthy": False,
                "is_plant": False,
                "status": "No Plant Detected",
                "badge": "warning",
                "description": "No plant leaf or crop foliage was detected in the camera frame. The AI model requires a plant leaf to perform disease analysis.",
                "possible_steps": "1. Hold a plant leaf directly in front of the camera.\n2. Ensure adequate lighting on the leaf.\n3. Avoid capturing human faces, room furniture, or background items.",
                "supplement_name": "N/A",
                "supplement_img": "",
                "supplement_prod_link": "#",
                "ai_report": None,
                "index": -1
            }

        label, confidence, idx = self.model.predict(frame_bgr, target_crop=target_crop)
        accepted = confidence >= config.CONFIDENCE_THRESHOLD
        is_healthy = "healthy" in label.lower()

        description = "No specific description available."
        possible_steps = "Keep monitoring plant condition and maintain standard irrigation."
        supplement_name = "N/A"
        supplement_img = ""
        supplement_prod_link = "#"

        if self.disease_info is not None and idx < len(self.disease_info):
            row = self.disease_info[idx]
            # Use plant_name/disease_name from CSV if present
            csv_name = row.get("disease_name", label)
            if isinstance(csv_name, str) and csv_name.strip():
                label = csv_name
            description = row.get("description", description)
            possible_steps = row.get("Possible Steps", possible_steps)

        if self.supplement_info is not None and idx < len(self.supplement_info):
            srow = self.supplement_info[idx]
            supplement_name = srow.get("supplement name", supplement_name)
            supplement_img = srow.get("supplement image", supplement_img)
            supplement_prod_link = srow.get("buy link", supplement_prod_link)

        ai_report = None
        if generate_ai_summary and not is_healthy:
            try:
                import ai_assistant
                ai_report = ai_assistant.generate_disease_ai_summary(
                    label=label,
                    confidence=round(confidence * 100, 1),
                    description=description,
                    steps=possible_steps,
                    supplement=supplement_name
                )
            except Exception as e:
                print(f"AI report generation warning: {e}")

        return {
            "label": label,
            "confidence": round(confidence * 100, 1),
            "confidence_ratio": float(confidence),
            "accepted": accepted,
            "is_healthy": is_healthy,
            "is_plant": True,
            "status": "Healthy Plant" if is_healthy else "Plant Stress / Disease Detected",
            "badge": "success" if is_healthy else ("danger" if confidence >= 0.7 else "warning"),
            "description": description,
            "possible_steps": possible_steps,
            "supplement_name": supplement_name,
            "supplement_img": supplement_img,
            "supplement_prod_link": supplement_prod_link,
            "ai_report": ai_report,
            "index": idx
        }

    def is_healthy(self, label: str) -> bool:
        return "healthy" in label.lower()

