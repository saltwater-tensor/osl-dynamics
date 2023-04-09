"""TDE-DyNeMo.

In this script we train a DyNeMo model on time-delay embedded data.
We will use source reconstructed resting-state MEG data. See the
examples/toolbox_paper/get_data.py script for how to download the training data.
"""

from osl_dynamics import run_pipeline

config = """
    load_data:
        data_dir: training_data
        data_kwargs: {n_jobs: 16}
        prepare_kwargs:
            n_embeddings: 15
            n_pca_components: 80
    train_dynemo:
        config_kwargs:
            n_modes: 8
            learn_means: False
            learn_covariances: True
    regression_spectra:
        kwargs:
            sampling_frequency: 250
            frequency_range: [1, 45]
            n_jobs: 16
    plot_tde_dynemo_networks:
        mask_file: MNI152_T1_8mm_brain.nii.gz
        parcellation_file: fmri_d100_parcellation_with_3PCC_ips_reduced_2mm_ss5mm_ds8mm_adj.nii.gz
"""
run_pipeline(config, output_dir="results/tde_dynemo")
