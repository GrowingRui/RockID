"""tensorflowjs_converter with its optional heavy imports stubbed out.

tensorflowjs imports TF Decision Forests and JAX at module load, although they are only needed to
convert those model types. Their pins (e.g. tensorflow-decision-forests -> an exact TensorFlow)
make `pip install tensorflowjs` fight the training TensorFlow. With `pip install --no-deps
tensorflowjs` plus the stubs below, the converter runs on the same TensorFlow that wrote the
SavedModel. Usage: python tfjs_convert.py <tensorflowjs_converter args>"""

import sys
import types

# Stub the converter's JAX entry point, not `jax` itself: Keras probes the real jax package.
jax_conversion = types.ModuleType("tensorflowjs.converters.jax_conversion")
jax_conversion.convert_jax = None
sys.modules.setdefault("tensorflowjs.converters.jax_conversion", jax_conversion)
sys.modules.setdefault("tensorflow_decision_forests", types.ModuleType("tensorflow_decision_forests"))

from tensorflowjs.converters import converter  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "tensorflowjs_converter"
    converter.pip_main()
