"""TF.js export smoke test, run *before* training (Phase 2 acceptance).

Exports an untrained model as a SavedModel, converts it to a quantized TF.js graph model
with the tensorflowjs converter (installed with --no-deps and run through `scripts/tfjs_convert.py`,
so it uses the training TensorFlow and can't replace it), runs it in Node with @tensorflow/tfjs and
compares the output to Keras. Passing means this
TensorFlow / Keras / converter combination works end to end; the versions are then pinned."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    return r


def export_saved_model(model, out_dir: Path) -> Path:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    if hasattr(model, "export"):  # Keras 3
        model.export(str(out_dir), format="tf_saved_model", verbose=False)
    else:  # Keras 2 (tf_keras)
        import tensorflow as tf
        tf.saved_model.save(model, str(out_dir))
    return out_dir


def ensure_converter(spec: str) -> dict:
    """Installs `spec` (e.g. tensorflowjs==4.22.0) and its light dependencies with --no-deps, so pip
    never touches the installed TensorFlow. Returns the converter version."""
    import tensorflow as tf

    tf_minor = ".".join(tf.__version__.split(".")[:2])
    wanted = {"tensorflowjs": spec, "tensorflow_hub": "tensorflow_hub", "tf_keras": f"tf_keras~={tf_minor}.0",
              "packaging": "packaging", "six": "six", "pkg_resources": "setuptools<81"}
    missing = [pkg for mod, pkg in wanted.items() if importlib.util.find_spec(mod) is None]
    if missing:
        _run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", *missing])
    importlib.invalidate_caches()
    # Read the version from metadata: importing tensorflowjs here would hit the imports the wrapper stubs.
    return {"tensorflowjs": importlib.metadata.version("tensorflowjs"), "installed": missing}


def convert(saved_model: Path, out_dir: Path, wrapper: Path, quantization: str = "float16") -> Path:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    _run([sys.executable, wrapper, "--input_format=tf_saved_model",
          "--output_format=tfjs_graph_model", "--signature_name=serving_default", "--saved_model_tags=serve",
          *([f"--quantize_{quantization}=*"] if quantization != "none" else []), saved_model, out_dir])
    return out_dir


def dir_size_mb(d: Path) -> float:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 2**20


def ensure_node_tfjs(work: Path, npm_spec: str, script: Path) -> dict:
    """Installs @tensorflow/tfjs (pure JS, CPU backend, no native build) next to a copy of the script."""
    if shutil.which("node") is None or shutil.which("npm") is None:
        raise RuntimeError("node/npm not found; install Node.js")
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(script, work / script.name)
    if not (work / "node_modules" / "@tensorflow" / "tfjs").exists():
        (work / "package.json").write_text('{"private": true, "type": "module"}')
        _run([shutil.which("npm"), "install", "--silent", "--no-audit", "--no-fund", npm_spec], cwd=work)
    pkg = json.loads((work / "node_modules" / "@tensorflow" / "tfjs" / "package.json").read_text())
    return {"node": _run([shutil.which("node"), "--version"]).stdout.strip(), "tfjs_npm": pkg["version"]}


def node_predict(tfjs_dir: Path, x: np.ndarray, work: Path, script_name: str = "tfjs_predict.mjs") -> tuple[np.ndarray, dict]:
    x = np.ascontiguousarray(x, dtype=np.float32)
    (work / "input.bin").write_bytes(x.tobytes())
    (work / "input.json").write_text(json.dumps(list(x.shape)))
    r = _run([shutil.which("node"), work / script_name, tfjs_dir.resolve(), work / "input.bin", work / "input.json", work / "output.bin"], cwd=work)
    info = json.loads(r.stdout.strip().splitlines()[-1])
    y = np.frombuffer((work / "output.bin").read_bytes(), dtype=np.float32).reshape(info["outputShape"])
    return y, info


def softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def run_smoke_test(model, work: Path, cfg, scripts: Path, n_images: int = 4) -> dict:
    """Full check on `model` (untrained is fine). Returns a result dict with `ok` and the versions to pin."""
    import tensorflow as tf

    res: dict = {"versions": {"python": platform.python_version(), "tensorflow": tf.__version__,
                              "keras": getattr(tf.keras, "__version__", "unknown"), "numpy": np.__version__}}
    sm = export_saved_model(model, work / "saved_model")
    res["versions"]["converter"] = ensure_converter(cfg.tfjs_converter)
    tj = convert(sm, work / "tfjs", scripts / "tfjs_convert.py", cfg.tfjs_quantization)
    res["quantization"] = cfg.tfjs_quantization
    res["size_mb"] = round(dir_size_mb(tj), 2)
    res["n_weight_shards"] = len(list(tj.glob("*.bin")))

    rng = np.random.default_rng(0)
    x = rng.integers(0, 256, (n_images, cfg.image_size, cfg.image_size, 3)).astype(np.float32)
    ref = softmax(np.asarray(model(x, training=False)))
    try:
        res["versions"]["node"] = ensure_node_tfjs(work / "node", cfg.tfjs_npm, scripts / "tfjs_predict.mjs")
        out, info = node_predict(tj, x, work / "node")
        prob = softmax(out)
        res.update(node_backend=info["backend"], node_inputs=info["inputs"],
                   max_abs_diff=float(np.abs(prob - ref).max()),
                   argmax_agree=float((prob.argmax(1) == ref.argmax(1)).mean()))
        ran = out.shape == ref.shape
    except RuntimeError as e:
        res["node_error"] = str(e)[:2000]
        ran = False
    res["size_ok"] = res["size_mb"] <= cfg.max_web_model_mb
    res["parity_ok"] = bool(ran and res["max_abs_diff"] <= cfg.tfjs_max_abs_diff)
    res["ok"] = bool(ran and res["size_ok"] and res["parity_ok"])
    return res
