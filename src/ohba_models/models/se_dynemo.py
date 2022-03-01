"""Model class for an subject embedding extension of RIGO
"""
from dataclasses import dataclass
from typing import Literal

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers
from tqdm import trange
from ohba_models.models import dynemo_obs
from ohba_models.models.mod_base import BaseModelConfig
from ohba_models.models.inf_mod_base import InferenceModelConfig, InferenceModelBase
from ohba_models.inference.layers import (
    InferenceRNNLayer,
    LogLikelihoodLossLayer,
    MeanVectorsLayer,
    CovarianceMatricesLayer,
    MixVectorsLayer,
    MixMatricesLayer,
    ModelRNNLayer,
    NormalizationLayer,
    KLDivergenceLayer,
    KLLossLayer,
    SampleNormalDistributionLayer,
    SoftmaxLayer,
    ScalarLayer,
    MixSubjectEmbeddingParametersLayer,
    ConcatenateLayer,
)


@dataclass
class Config(BaseModelConfig, InferenceModelConfig):
    """Settings for SERIGO.

    Parameters
    ----------
    n_modes : int
        Number of modes.
    n_channels : int
        Number of channels.
    sequence_length : int
        Length of sequence passed to the inference network and generative model.
    
    inference_rnn : str
        RNN to use, either 'gru' or 'lstm'.
    inference_n_layers : int
        Number of layers.
    inference_n_untis : int
        Number of units.
    inference_normalization : str
        Type of normalization to use. Either None, 'batch' or 'layer'.
    inference_activation : str
        Type of activation to use after normalization and before dropout.
        E.g. 'relu', 'elu', etc.
    inference_dropout_rate : float
        Dropout rate.
    model_rnn : str
        RNN to use, either 'gru' or 'lstm'.
    model_n_layers : int
        Number of layers.
    model_n_units : int
        Number of units.
    model_normalization : str
        Type of normalization to use. Either None, 'batch' or 'layer'.
    model_activation : str
        Type of activation to use after normalization and before dropout.
        E.g. 'relu', 'elu', etc.
    model_dropout_rate : float
        Dropout rate.

    theta_normalization : str
        Type of normalization to apply to the posterior samples, theta.
        Either 'layer', 'batch' or None.
    alpha_xform : str
        Functional form of alpha. Either 'gumbel-softmax', 'softmax' or 'softplus'.
    learn_alpha_temperature : bool
        Should we learn the alpha temperature when alpha_xform='softmax' or
        'gumbel-softmax'?
    initial_alpha_temperature : float
        Initial value for the alpha temperature.

    learn_means : bool
        Should we make the mean vectors for each mode trainable?
    learn_covariances : bool
        Should we make the covariance matrix for each mode trainable?
    initial_means : np.ndarray
        Initialisation for mean vectors.
    initial_covariances : np.ndarray
        Initialisation for mode covariances.

    do_kl_annealing : bool
        Should we use KL annealing during training?
    kl_annealing_curve : str
        Type of KL annealing curve. Either 'linear' or 'tanh'.
    kl_annealing_sharpness : float
        Parameter to control the shape of the annealing curve if
        kl_annealing_curve='tanh'.
    n_kl_annealing_epochs : int
        Number of epochs to perform KL annealing.

    batch_size : int
        Mini-batch size.
    learning_rate : float
        Learning rate.
    gradient_clip : float
        Value to clip gradients by. This is the clipnorm argument passed to
        the Keras optimizer. Cannot be used if multi_gpu=True.
    n_epochs : int
        Number of training epochs.
    optimizer : str or tensorflow.keras.optimizers.Optimizer
        Optimizer to use. 'adam' is recommended.
    multi_gpu : bool
        Should be use multiple GPUs for training?
    strategy : str
        Strategy for distributed learning.

    n_subjects : int
        Number of subjects
    embedding_dim : int
        Number of dimensions for the subject embedding
    learn_between_subject_variance : bool
        Should we make the between_subject_variance trainable?
    intial_between_subject_variance : float
        Initialisation for the betwen subject variance.
    """

    # Inference network parameters
    inference_rnn: Literal["gru", "lstm"] = None
    inference_n_layers: int = 1
    inference_n_units: int = None
    inference_normalization: Literal[None, "batch", "layer"] = None
    inference_activation: str = None
    inference_dropout_rate: float = 0.0

    # Model network parameters
    model_rnn: Literal["gru", "lstm"] = None
    model_n_layers: int = 1
    model_n_units: int = None
    model_normalization: Literal[None, "batch", "layer"] = None
    model_activation: str = None
    model_dropout_rate: float = 0.0

    # Observation model parameters
    multiple_scales: bool = False
    learn_means: bool = None
    learn_covariances: bool = None
    initial_means: np.ndarray = None
    initial_covariances: np.ndarray = None

    # Parameters specific to subject embedding model
    n_subjects: int = None
    embedding_dim: int = None
    learn_between_subject_std: bool = None
    initial_between_subject_std: float = None

    def __post_init__(self):
        self.validate_rnn_parameters()
        self.validate_observation_model_parameters()
        self.validate_alpha_parameters()
        self.validate_kl_annealing_parameters()
        self.validate_dimension_parameters()
        self.validate_training_parameters()
        self.validate_subject_embedding_parameters()

    def validate_rnn_parameters(self):
        if self.inference_rnn is None or self.model_rnn is None:
            raise ValueError("Please pass inference_rnn and model_rnn.")

        if self.inference_n_units is None:
            raise ValueError("Please pass inference_n_units.")

        if self.model_n_units is None:
            raise ValueError("Please pass model_n_units.")

    def validate_observation_model_parameters(self):
        if self.learn_means is None or self.learn_covariances is None:
            raise ValueError("learn_means and learn_covariances must be passed.")

    def validate_subject_embedding_parameters(self):
        if (
            self.n_subjects is None
            or self.embedding_dim is None
            or self.learn_between_subject_std is None
        ):
            raise ValueError(
                "n_subjects, embedding_dim and learn_between_subject_std must be passed."
            )


class Model(InferenceModelBase):
    """Subject Embedded RNN Inference/model network and Gaussian observatons (SERIGO).
    Parameters
    ----------
    config : dynemo.models.serigo.Config
    """

    def __init__(self, config):
        super().__init__(config)

    def build_model(self):
        """Builds a keras model."""
        self.model = _model_structure(self.config)


def _model_structure(config):

    # layers for inputs
    data = layers.Input(shape=(config.sequence_length, config.n_channels), name="data")
    subj_id = layers.Input(shape=(config.sequence_length,), name="subj_id")

    # Inference RNN:
    # - Learns q(theta) ~ N(theta | inf_mu, inf_sigma), where
    #     - inf_mu    ~ affine(RNN(data_<=t))
    #     - inf_sigma ~ softplus(RNN(data_<=t))

    # Definition of layers
    inference_input_dropout_layer = layers.Dropout(
        config.inference_dropout_rate, name="data_drop"
    )
    inference_output_layer = InferenceRNNLayer(
        config.inference_rnn,
        config.inference_normalization,
        config.inference_activation,
        config.inference_n_layers,
        config.inference_n_units,
        config.inference_dropout_rate,
        name="inf_rnn",
    )
    inf_mu_layer = layers.Dense(config.n_modes, name="inf_mu")
    inf_sigma_layer = layers.Dense(
        config.n_modes, activation="softplus", name="inf_sigma"
    )

    # Layers to sample theta from q(theta) and to convert to mode mixing
    # factors alpha
    theta_layer = SampleNormalDistributionLayer(name="theta")
    theta_norm_layer = NormalizationLayer(config.theta_normalization, name="theta_norm")
    alpha_layer = ThetaActivationLayer(
        config.alpha_xform,
        config.initial_alpha_temperature,
        config.learn_alpha_temperature,
        name="alpha",
    )

    # Data flow
    inference_input_dropout = inference_input_dropout_layer(data)
    inference_output = inference_output_layer(inference_input_dropout)
    inf_mu = inf_mu_layer(inference_output)
    inf_sigma = inf_sigma_layer(inference_output)
    theta = theta_layer([inf_mu, inf_sigma])
    theta_norm = theta_norm_layer(theta)
    alpha = alpha_layer(theta_norm)

    # Subject embedding layer
    subject_embedding_layer = layers.Embedding(config.n_subjects, config.embedding_dim)

    # Data flow
    subject_embeddings = subject_embedding_layer(np.arange(config.n_subjects))

    # Observation model:
    # - Like in RIGO, we use a multivariate normal, but the mean vector and the covariance
    #   matrix also depend on the subject embedding vectors

    # Definition of layers
    group_means_layer = MeanVectorsLayer(
        config.n_modes,
        config.n_channels,
        config.learn_means,
        config.initial_means,
        name="group_means",
    )
    group_covs_layer = CovarianceMatricesLayer(
        config.n_modes,
        config.n_channels,
        config.learn_covariances,
        config.initial_covariances,
        name="group_covs",
    )
    between_subject_std_layer = ScalarLayer(
        config.learn_between_subject_std,
        config.initial_between_subject_std,
        name="between_subject_std",
    )
    mix_subject_embedding_parameters_layer = MixSubjectEmbeddingParametersLayer(
        config.n_modes, config.n_channels, config.n_subjects, name="mix_se_parameters"
    )
    ll_loss_layer = LogLikelihoodLossLayer(name="ll_loss")

    # Data flow
    group_mu = group_means_layer(data)  # data not used
    group_D = group_covs_layer(data)  # data not used
    b_sigma = between_subject_std_layer(data)  # data not used
    m, C = mix_subject_embedding_parameters_layer(
        [alpha, group_mu, group_D, b_sigma, subject_embeddings, subj_id]
    )
    ll_loss = ll_loss_layer([data, m, C])

    # Model RNN
    # p(theta_t | theta_<t, s_<t) ~ N(theta_t | mod_mu, mod_sigma), where
    #   mod_mu ~ affine( Concat( RNN(theta_<t), s_t) )
    #   mod_sigma ~ softplus(affine( Concat( RNN(theta_<t), s_t) ))

    # Definition of layers
    model_input_dropout_layer = layers.Dropout(
        config.model_dropout_rate, name="theta_norm_drop"
    )
    model_output_layer = ModelRNNLayer(
        config.model_rnn,
        config.model_normalization,
        config.model_activation,
        config.model_n_layers,
        config.model_n_units,
        config.model_dropout_rate,
        name="mod_rnn",
    )
    concatenate_layer = ConcatenateLayer(axis=2, name="model_concat")
    mod_mu_layer = layers.Dense(config.n_modes, name="mod_mu")
    mod_sigma_layer = layers.Dense(
        config.n_modes, activation="softplus", name="mod_sigma"
    )
    kl_div_layer = KLDivergenceLayer(name="kl_div")
    kl_loss_layer = KLLossLayer(config.do_kl_annealing, name="kl_loss")

    # Data flow
    model_input_dropout = model_input_dropout_layer(theta_norm)
    model_output = model_output_layer(model_input_dropout)
    dynamic_subject_embedding = subject_embedding_layer(subj_id)
    model_output_concat = concatenate_layer([model_output, dynamic_subject_embedding])
    mod_mu = mod_mu_layer(model_output_concat)
    mod_sigma = mod_sigma_layer(model_output_concat)
    kl_div = kl_div_layer([inf_mu, inf_sigma, mod_mu, mod_sigma])
    kl_loss = kl_loss_layer(kl_div)

    return tf.keras.Model(
        inputs=[data, subj_id], outputs=[ll_loss, kl_loss, alpha], name="SERIGO"
    )
