# image_search_implementation_v2/embedder.py
from pathlib import Path
import torch
import numpy as np

_model = None
_processor = None

def load_clip(model_name: str):
    global _model, _processor
    if _model is None or _processor is None:
        from transformers import CLIPProcessor, CLIPModel
        _processor = CLIPProcessor.from_pretrained(model_name)
        _model = CLIPModel.from_pretrained(model_name)
        _model.to(torch.device("cpu"))
        _model.eval()
    return _model, _processor


def _normalize_feature_output(feats):
    """Return a torch tensor regardless of HF output shape/version."""
    if feats is None:
        return None
    if torch.is_tensor(feats):
        return feats
    if hasattr(feats, "pooler_output") and feats.pooler_output is not None:
        return feats.pooler_output
    if hasattr(feats, "last_hidden_state") and feats.last_hidden_state is not None:
        return feats.last_hidden_state[:, 0, :]
    if isinstance(feats, (tuple, list)) and feats:
        first = feats[0]
        if torch.is_tensor(first):
            return first
    return None


def embed_image(path: Path, model_name: str):
    try:
        model, processor = load_clip(model_name)
        from PIL import Image
        img = Image.open(path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt", padding=True)
        inputs = {k: v.to(torch.device("cpu")) for k, v in inputs.items()}
        with torch.no_grad():
            feats = model.get_image_features(**inputs)
        feats = _normalize_feature_output(feats)
        if feats is None:
            raise RuntimeError("image features unavailable from model output")
        feats = feats / (feats.norm(dim=-1, keepdim=True) + 1e-12)
        vec = feats.squeeze(0).cpu().numpy().astype(np.float32)
        return vec
    except Exception as e:
        # return None on failure
        print("embed_image failed:", e)
        return None
