"""
Example use of DyNeMo on reduced sensor space data.
The resulting C(t) matrix can be used for
TASER (Temporally Adaptive SourcE Reconstruction).

Please also see make_default_settings.py to configure run-time defaults.

Ryan Timms, OHBA, 2021. @blobsonthebrain
"""
# TODO: This example is out of date.
# flake8: noqa
print("Setting up")
import pathlib

import matplotlib.pyplot as plt
import numpy as np
import scipy.io as spio
import tensorflow as tf
import dynemo
import yaml
from dynemo import data, files
from dynemo.inference import tf_ops
from dynemo.models import RIGO
from dynemo.utils import plotting

tf.keras.backend.clear_session()

default_settings = files.example.path / "default_TABFER_settings.yaml"
results_folder_name = "example_results"

# GPU settings
tf_ops.gpu_growth()
multi_gpu = True

# Load in run-time settings.
settings = yaml.safe_load(default_settings.open())
print(f"Loaded default settings from {default_settings}.")

# Settings
n_modes = settings["n_modes"]
sequence_length = settings["sequence_length"]
batch_size = settings["batch_size"]
n_layers_inference = settings["n_layers_inference"]
n_layers_model = settings["n_layers_model"]
n_units_inference = settings["n_units_inference"]
n_units_model = settings["n_units_model"]
do_kl_annealing = settings["do_kl_annealing"]
kl_annealing_sharpness = settings["kl_annealing_sharpness"]
n_epochs = settings["n_epochs"]
n_epochs_kl_annealing = settings["n_epochs_kl_annealing"]
rnn_type = settings["rnn_type"]
rnn_normalization = settings["rnn_normalization"]
theta_normalization = settings["theta_normalization"]
dropout_rate_inference = settings["dropout_rate_inference"]
dropout_rate_model = settings["dropout_rate_model"]
learn_means = settings["learn_means"]
learn_covariances = settings["learn_covariances"]
alpha_xform = settings["alpha_xform"]
learn_alpha_scaling = settings["learn_alpha_scaling"]
normalize_covariances = settings["normalize_covariances"]
learning_rate = settings["learning_rate"]
learn_alpha_temperature = settings["learn_alpha_temperature"]
initial_alpha_temperature = settings["initial_alpha_temperature"]
cov_init_type = "random"

# Load functional data from a pre-processed MATLAB object
Y = spio.loadmat("/well/woolrich/shared/TASER/example_data/filtered_motor_data.mat")
Y = Y["reduced_data"]  # needs to be channels (or PCs) by time

# Prepare the data for DyNeMo, making a training and prediction dataset
print("Reading MEG data")
prepared_data = data.Data(Y[np.newaxis])
n_channels = prepared_data.n_channels
training_dataset = prepared_data.dataset(sequence_length, batch_size, shuffle=True)
prediction_dataset = prepared_data.dataset(sequence_length, batch_size, shuffle=False)

if cov_init_type == "random":
    # Use random covariances for the initialisation.
    # Use the same initialisation from disk for reproducibility
    rand_init = spio.loadmat("/well/woolrich/shared/TASER/example_data/rand_init.mat")
    rand_init = rand_init["rand_init"]  # needs to be channels or PCs by time

    # Ensure data are PSD
    for i in range(n_modes):
        rand_init[i, :, :] = np.linalg.cholesky(
            rand_init[i, :, :] + (1e-5 * np.eye(n_channels))
        )
    initial_covariances = rand_init.astype("float32")
else:
    initial_covariances = np.tile(np.eye(n_channels), (n_modes, 1, 1))

initial_means = np.zeros((n_modes, n_channels))


# Build model
model = RIGO(
    n_channels=n_channels,
    n_modes=n_modes,
    sequence_length=sequence_length,
    learn_covariances=learn_covariances,
    initial_covariances=initial_covariances,
    rnn_type=rnn_type,
    rnn_normalization=rnn_normalization,
    n_layers_inference=n_layers_inference,
    n_layers_model=n_layers_model,
    n_units_inference=n_units_inference,
    n_units_model=n_units_model,
    dropout_rate_inference=dropout_rate_inference,
    dropout_rate_model=dropout_rate_model,
    theta_normalization=theta_normalization,
    alpha_xform=alpha_xform,
    learn_alpha_temperature=learn_alpha_temperature,
    alpha_temperature=initial_alpha_temperature,
    learn_alpha_scaling=learn_alpha_scaling,
    normalize_covariances=normalize_covariances,
    do_kl_annealing=do_kl_annealing,
    kl_annealing_sharpness=kl_annealing_sharpness,
    n_epochs_kl_annealing=n_epochs_kl_annealing,
    learning_rate=learning_rate,
    multi_gpu=multi_gpu,
)
model.summary()

# Train the model
history = model.fit(training_dataset, epochs=n_epochs)

# Get our inferred parameters
alpha = model.get_alpha(prediction_dataset)
covz = model.get_covariances()
kl = history.history["kl_loss"]
ll = history.history["ll_loss"]

# Plot the learnt dynamics and covariances as a set of scalp topographies
# Reshape the alphas s.t. they are trial-wise.
# The data is continuous and 3001 samples long per trial
trl_length = 3001
n_trials = int(np.floor(np.asarray(np.shape(alpha[:, 0])) / trl_length))
cropped_alphas = alpha[0 : n_trials * trl_length, :]
tw_alphas = np.reshape(cropped_alphas, (n_trials, trl_length, n_modes))
plt.figure(figsize=(10, 20))
for i in range(n_modes):
    plt.subplot(n_modes, 1, i + 1)
    plt.plot(np.mean(tw_alphas, 0)[:, i])
    plt.title("Mode " + str(i))
plt.xlabel("Time (s)")
plt.suptitle("Inferred trial-wise dynamics")
plt.tight_layout()

U = spio.loadmat("/well/woolrich/shared/TASER/example_data/projector.mat")
U = U["projector"]  # needs to be channels or PCs by time

chan_names = spio.loadmat(
    "/well/woolrich/shared/TASER/example_data/chan_names.mat"
)  # Channels to include in plot
chan_names = chan_names["ans"][0]
ctf275_channel_names = [chan_name[0] for chan_name in chan_names]

for ii in range(n_modes):
    # Project back to the full-space
    tmp = covz[ii, :, :]
    res = np.matmul(np.matmul(np.transpose(U), tmp), U)

    # Get the diagonal from the inferred covariance matrices
    ctf275_data = np.diag(res)

    # Produce the figure using the "CTF275_helmet"
    # layout provided by the FieldTrip toolbox
    plotting.topoplot(
        layout="CTF275_helmet",
        data=ctf275_data,
        channel_names=ctf275_channel_names,
        plot_boxes=False,
        show_deleted_sensors=True,
        show_names=False,
        title="Mode " + str(ii),
        colorbar=True,
        cmap="plasma",
        n_contours=25,
    )

# And save the results to disk.
# Also make a copy of the run-time settings in the same directory.
pathlib.Path(results_folder_name).mkdir(exist_ok=True)
np.save(results_folder_name + "/alphas.npy", alpha)
np.save(results_folder_name + "/covariances.npy", covz)
np.save(results_folder_name + "/KL.npy", kl)
np.save(results_folder_name + "/LL.npy", ll)