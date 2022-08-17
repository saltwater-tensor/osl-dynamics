"""Example script for running inference on simulated MDyn_HMM_MVN data.

- Multi-dynamic version for dynemo_hmm-mvn.py
- Should achieve a dice of ~0.99 for alpha and ~0.99 for gamma.
"""

print("Setting up")
from osl_dynamics import data, simulation
from osl_dynamics.inference import metrics, modes, tf_ops
from osl_dynamics.models.mdynemo import Config, Model

# GPU settings
tf_ops.gpu_growth()

# Settings
config = Config(
    n_modes=5,
    n_channels=20,
    sequence_length=100,
    inference_n_units=128,
    inference_normalization="layer",
    model_n_units=128,
    model_normalization="layer",
    theta_normalization="layer",
    learn_alpha_temperature=True,
    initial_alpha_temperature=1.0,
    learn_means=True,
    learn_stds=True,
    learn_fcs=True,
    do_kl_annealing=True,
    kl_annealing_curve="tanh",
    kl_annealing_sharpness=10,
    n_kl_annealing_epochs=100,
    batch_size=16,
    learning_rate=0.01,
    n_epochs=200,
)

# Simulate data
print("Simulating data")
sim = simulation.MDyn_HMM_MVN(
    n_samples=25600,
    n_modes=config.n_modes,
    n_channels=config.n_channels,
    trans_prob="sequence",
    stay_prob=0.9,
    means="random",
    covariances="random",
    random_seed=123,
)
sim.standardize()
training_data = data.Data(sim.time_series)

# Build model
model = Model(config)
model.summary()

# Set regularisers
model.set_regularizers(training_data)

print("Training model")
history = model.fit(training_data)

# Free energy = Log Likelihood - KL Divergence
free_energy = model.free_energy(training_data)
print(f"Free energy: {free_energy}")

# Inferred mode mixing factors
inf_alpha, inf_gamma = model.get_mode_time_courses(training_data)

inf_alpha = modes.argmax_time_courses(inf_alpha)
inf_gamma = modes.argmax_time_courses(inf_gamma)

# Simulated mode mixing factors
sim_alpha, sim_gamma = sim.mode_time_course

# Match the inferred and simulated mixing factors
sim_alpha, inf_alpha = modes.match_modes(sim_alpha, inf_alpha)
sim_gamma, inf_gamma = modes.match_modes(sim_gamma, inf_gamma)

# Dice coefficients
dice_alpha = metrics.dice_coefficient(sim_alpha, inf_alpha)
dice_gamma = metrics.dice_coefficient(sim_gamma, inf_gamma)

print("Dice coefficient for mean:", dice_alpha)
print("Dice coefficient for fc:", dice_gamma)

# Fractional occupancies
fo_sim_alpha = modes.fractional_occupancies(sim_alpha)
fo_sim_gamma = modes.fractional_occupancies(sim_gamma)

fo_inf_alpha = modes.fractional_occupancies(inf_alpha)
fo_inf_gamma = modes.fractional_occupancies(inf_gamma)

print("Fractional occupancies mean (Simulation):", fo_sim_alpha)
print("Fractional occupancies mean (DyNeMo):", fo_inf_alpha)

print("Fractional occupancies fc (Simulation):", fo_sim_gamma)
print("Fractional occupancies fc (DyNeMo):", fo_inf_gamma)
