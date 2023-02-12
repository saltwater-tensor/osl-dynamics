"""Initializers for TensorFlow layers.

"""

import numpy as np
import tensorflow_probability as tfp
import tensorflow as tf
from tensorflow.keras import Model, layers, initializers
from tensorflow.keras.initializers import Initializer
from osl_dynamics import inference

tfb = tfp.bijectors


class WeightInitializer(Initializer):
    """Initialize weights to given value.

    Parameters
    ----------
    initial_value : numpy.ndarray
        Value to initialise weights to.
        Note, the shape is not checked.
    """

    def __init__(self, initial_value):
        self.initial_value = initial_value

    def __call__(self, shape, dtype=None):
        return self.initial_value


class IdentityCholeskyInitializer(Initializer):
    """Initialize weights to a flattened cholesky factor of identity matrices."""

    def __init__(self):
        # Bijector used to transform learnable vectors to covariance matrices
        self.bijector = tfb.Chain([tfb.CholeskyOuterProduct(), tfb.FillScaleTriL()])

    def __call__(self, shape, dtype=None):
        n = shape[0]  # n_modes
        m = int(np.sqrt(1 + 8 * shape[1]) / 2 - 0.5)  # n_channels
        diagonals = np.ones([n, m])
        matrices = np.array([np.diag(d) for d in diagonals], dtype=np.float32)
        return self.bijector.inverse(matrices)


class NormalIdentityCholeskyInitializer(Initializer):
    """Initialize weights to a flattened cholesky factor of identity
    matrices with a normal error added to the diagonal.

    Parameters
    ----------
    std : float
        Standard deviation of the error to add.
    """

    def __init__(self, std):
        self.std = std

        # Bijector used to transform learnable vectors to covariance matrices
        self.bijector = tfb.Chain([tfb.CholeskyOuterProduct(), tfb.FillScaleTriL()])

    def __call__(self, shape, dtype=None):
        n = shape[0]  # n_modes
        m = int(np.sqrt(1 + 8 * shape[1]) / 2 - 0.5)  # n_channels
        diagonals = initializers.TruncatedNormal(mean=1, stddev=self.std).__call__(
            shape=(n, m), dtype=tf.float32
        )
        matrices = np.array([np.diag(d) for d in diagonals], dtype=np.float32)
        return self.bijector.inverse(matrices)


class NormalCorrelationCholeskyInitializer(Initializer):
    """Initialize weights to a flattened cholesky factor of correlation
    matrices with a normal error added to the flattened cholesky factor.

    Parameters
    ----------
    mean : float
        Mean of the error to add.
    std : float
        Standard deviation of the error to add.
    """

    def __init__(self, std):
        self.std = std

        # Bijector used to transform learnable vectors to covariance matrices
        self.bijector = tfb.Chain(
            [tfb.CholeskyOuterProduct(), tfb.CorrelationCholesky()]
        )

    def __call__(self, shape, dtype=None):
        n = shape[0]  # n_modes
        m = int(np.sqrt(1 + 8 * shape[1]) / 2 + 0.5)  # n_channels
        diagonals = np.ones([n, m])
        matrices = np.array([np.diag(d) for d in diagonals], dtype=np.float32)
        cholesky_factors = self.bijector.inverse(matrices)
        cholesky_factors += initializers.TruncatedNormal(
            mean=0, stddev=self.std
        ).__call__(shape=cholesky_factors.shape, dtype=tf.float32)
        return cholesky_factors


class NormalDiagonalInitializer(Initializer):
    """Initializer for diagonal matrices with a normal error added.

    Parameters
    ----------
    std : float
        Standard deviation of the error to add.
    """

    def __init__(self, std):
        self.std = std

        # Softplus transformation to ensure diagonal is positive
        self.bijector = tfb.Softplus()

    def __call__(self, shape, dtype=None):
        n = shape[0]  # n_modes
        m = shape[1]  # n_channels
        diagonals = initializers.TruncatedNormal(mean=1, stddev=self.std).__call__(
            shape=(n, m), dtype=tf.float32
        )
        return self.bijector.inverse(diagonals)


class SoftplusNormalInitializer(Initializer):
    def __init__(self, mean=0, std=1):
        self.mean = mean
        self.std = std
        self.bijector = tfb.Softplus()

    def __call__(self, shape, dtype=None):
        x = initializers.TruncatedNormal(mean=self.mean, stddev=self.std).__call__(
            shape=shape, dtype=tf.float32
        )
        return self.bijector(x)


class CopyTensorInitializer(Initializer):
    """Initialize weights to another Tensor's value.

    Parameters
    ----------
    tensor : tensorflow.Tensor
        Tensor to copy.
    """

    def __init__(self, tensor):
        self.tensor = tensor

    def __call__(self, shape, dtype=None):
        return self.tensor.read_value()


def reinitialize_layer_weights(layer):
    """Re-initializes the weights in a particular layer.

    This function relies on each layer having an initializer attribute.
    Therefore, you must specify a self.*_initializer attribute in custom
    layers, otherwise this function will break.

    Parameters
    ----------
    layer: tensorflow.keras.layers.Layer
        Layer to initialize weights for.
    """

    # Get the initialisation container
    if hasattr(layer, "cell"):
        init_container = layer.cell
    else:
        init_container = layer

    # Re-initialise
    for key, initializer in init_container.__dict__.items():
        if "initializer" not in key:
            continue
        if key == "recurrent_initializer":
            var = getattr(init_container, "recurrent_kernel")
        else:
            var = getattr(init_container, key.replace("_initializer", ""))
        var.assign(initializer(var.shape, var.dtype))


def reinitialize_model_weights(model, keep=None):
    """Re-initialize the weights in the model.

    Parameters
    ----------
    model : tensorflow.keras.Model
        Model to re-initialize weights for.
    keep : list
        List of str containing names for layers to not reinitialize.
    """
    if keep is None:
        keep = []

    for layer in model.layers:
        # Skip layers that we want to keep
        if layer.name in keep:
            continue

        # if this is just a single layer
        if not isinstance(layer, Model) and not ("layers" in dir(layer)):
            # If the layer in bidirectional we need to re_initialise the
            # forward and backward layers.
            if isinstance(layer, layers.Bidirectional):
                reinitialize_layer_weights(layer.forward_layer)
                reinitialize_layer_weights(layer.backward_layer)
            else:
                reinitialize_layer_weights(layer)
        # If the layer consists of multiple layers pass the layer back
        # to this function recursively
        else:
            reinitialize_model_weights(layer)
