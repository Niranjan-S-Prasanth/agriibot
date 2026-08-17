"""Loads and runs an ALREADY-TRAINED plant-disease model.

This is the one place your existing model plugs into the whole system.
Set MODEL_PATH and MODEL_TYPE in config.py — everything downstream
(disease_detector.py, main.py, dashboard.py's upload-check) calls the
same MLModel.predict(frame) regardless of what format your model is in,
so nothing else needs to change.

Supported formats (set config.MODEL_TYPE, or leave "auto" to detect from
the file extension):
    "tflite"     -> a .tflite file
    "keras"      -> a .h5 or .keras file (tf.keras.models.load_model)
    "savedmodel" -> a TensorFlow SavedModel folder
    "onnx"       -> a .onnx file (needs `pip install onnxruntime`)

If your model is something else entirely (a plain pickled sklearn model,
a PyTorch .pt, etc.), add a branch in _load_model() below — the rest of
the pipeline doesn't care, it only needs predict(frame_bgr) to return
(label, confidence).
"""
import os
import numpy as np
import config


class MLModel:
    def __init__(self, model_path=None, model_type=None):
        self.model_path = model_path or config.MODEL_PATH
        self.model_type = model_type or config.MODEL_TYPE
        if self.model_type == "auto":
            self.model_type = self._detect_type(self.model_path)

        self.backend = self.model_type
        self._load_model()

    def _detect_type(self, path):
        if os.path.isdir(path):
            return "savedmodel"
        ext = os.path.splitext(path)[1].lower()
        if ext == ".tflite":
            return "tflite"
        if ext in (".h5", ".keras"):
            return "keras"
        if ext == ".onnx":
            return "onnx"
        if ext in (".pth", ".pt"):
            return "pytorch"
        raise ValueError(
            f"Can't auto-detect model type for '{path}'. "
            f"Set config.MODEL_TYPE explicitly (pytorch/tflite/keras/savedmodel/onnx)."
        )

    def _load_model(self):
        if self.backend == "pytorch":
            import torch
            import torchvision.models as models
            from torchvision import transforms

            self.device = torch.device("cpu")
            num_classes = len(config.CLASS_NAMES) if config.CLASS_NAMES else 38
            self.torch_model = models.resnet18(pretrained=False)
            self.torch_model.fc = torch.nn.Linear(self.torch_model.fc.in_features, num_classes)
            
            if os.path.exists(self.model_path):
                checkpoint = torch.load(self.model_path, map_location=self.device)
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
                    self.torch_model.load_state_dict(checkpoint["state_dict"])
                else:
                    self.torch_model.load_state_dict(checkpoint)
            
            self.torch_model.eval()
            self.torch_model.to(self.device)
            self.in_h, self.in_w = 224, 224
            self.five_crop = transforms.FiveCrop(224)
            self.resize_256 = transforms.Resize(256)
            self.to_tensor = transforms.ToTensor()
            self.norm = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            self.center_crop_transform = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])

            # Plant species index ranges for 38-class PlantDoc model
            self.species_ranges = {
                'Apple': list(range(0, 4)),
                'Blueberry': [4],
                'Cherry': list(range(5, 7)),
                'Corn': list(range(7, 11)),
                'Grape': list(range(11, 15)),
                'Orange': [15],
                'Peach': list(range(16, 18)),
                'Pepper bell': list(range(18, 20)),
                'Potato': list(range(20, 23)),
                'Raspberry': [23],
                'Soybean': [24],
                'Squash': [25],
                'Strawberry': list(range(26, 28)),
                'Tomato': list(range(28, 38))
            }

        elif self.backend == "tflite":
            try:
                import tflite_runtime.interpreter as tflite
            except ImportError:
                import tensorflow.lite as tflite
            self.interpreter = tflite.Interpreter(model_path=self.model_path)
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()
            _, h, w, _ = self.input_details[0]["shape"]
            self.in_w, self.in_h = int(w), int(h)

        elif self.backend in ("keras", "savedmodel"):
            import tensorflow as tf
            self.model = tf.keras.models.load_model(self.model_path)
            shape = self.model.input_shape  # e.g. (None, 224, 224, 3)
            self.in_h, self.in_w = int(shape[1]), int(shape[2])

        elif self.backend == "onnx":
            import onnxruntime as ort
            self.session = ort.InferenceSession(self.model_path)
            self.input_name = self.session.get_inputs()[0].name
            shape = self.session.get_inputs()[0].shape  # e.g. [1,3,224,224] or [1,224,224,3]
            dims = [d for d in shape if isinstance(d, int) and d > 3]
            self.in_h, self.in_w = (dims[0], dims[1]) if len(dims) >= 2 else config.MODEL_INPUT_SIZE

        else:
            raise ValueError(f"Unknown MODEL_TYPE: {self.backend}")

    def preprocess(self, frame_bgr):
        import cv2
        img = cv2.resize(frame_bgr, (self.in_w, self.in_h))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return np.expand_dims(img, axis=0)

    def predict(self, frame_bgr, target_crop=None):
        """Returns (label, confidence, idx). Same signature no matter the backend."""
        if self.backend == "pytorch":
            import torch
            import cv2
            from PIL import Image
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            img_256 = self.resize_256(pil_img)
            
            # Five-Crop TTA + Center-Crop Ensemble
            crops = self.five_crop(img_256)
            crop_tensors = torch.stack([self.norm(self.to_tensor(c)) for c in crops]).to(self.device)
            single_tensor = self.center_crop_transform(pil_img).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                logits_five = self.torch_model(crop_tensors)
                probs_five = torch.softmax(logits_five, dim=1).mean(dim=0)
                
                logits_single = self.torch_model(single_tensor)[0]
                probs_single = torch.softmax(logits_single, dim=0)
                
                # Weighted ensemble: 60% center crop, 40% multi-crop TTA
                probs = (probs_single * 0.60 + probs_five * 0.40).cpu().numpy()
            
            if target_crop and target_crop in self.species_ranges:
                sp_indices = self.species_ranges[target_crop]
                idx = sp_indices[int(np.argmax(probs[sp_indices]))]
            else:
                # Species aggregation check
                species_probs = {}
                for sp, indices in self.species_ranges.items():
                    species_probs[sp] = float(np.sum(probs[indices]))
                best_sp = max(species_probs, key=species_probs.get)
                
                top1_idx = int(np.argmax(probs))
                
                # If top1 species matches best species, pick top1. Otherwise pick best disease in best species.
                if top1_idx in self.species_ranges[best_sp]:
                    idx = top1_idx
                else:
                    sp_indices = self.species_ranges[best_sp]
                    idx = sp_indices[int(np.argmax(probs[sp_indices]))]

            confidence = float(probs[idx])
        else:
            x = self.preprocess(frame_bgr)
            if self.backend == "tflite":
                self.interpreter.set_tensor(self.input_details[0]["index"], x)
                self.interpreter.invoke()
                out = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

            elif self.backend in ("keras", "savedmodel"):
                out = self.model.predict(x, verbose=0)[0]

            elif self.backend == "onnx":
                out = self.session.run(None, {self.input_name: x})[0][0]

            idx = int(np.argmax(out))
            confidence = float(out[idx])

        label = config.CLASS_NAMES[idx] if idx < len(config.CLASS_NAMES) else f"class_{idx}"
        return label, confidence, idx

