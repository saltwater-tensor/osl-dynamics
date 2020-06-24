import logging
from typing import Any, Union

import numpy as np
import scipy.io
from vrad.data.io import load_data
from vrad.data.manipulation import (
    pca,
    scale,
    standardize,
    trials_to_continuous,
    trim_trials,
)
from vrad.utils import plotting
from vrad.utils.decorators import auto_repr
from vrad.utils.misc import time_axis_first


class Data:
    """An object for storing time series data with various methods to act on it.

    Data is designed to standardize the workflow required to work with inputs with
    the format numpy.ndarray, numpy files, MAT (MATLAB) files, MATv7.3 files and
    SPM MEEG objects (also from MATLAB).

    If the input provided is a numpy.ndarray, it is taken as is. If the input is a
    string, VRAD will check the file extension to see if it is .npy (read by
    numpy.load) or .mat. If a .mat file is found, it is first opened using
    scipy.io.loadmat and if that fails, mat73.loadmat. Any input other than these is
    considered valid if it can be converted to a numpy array using numpy.array.

    When importing from MAT files, the values in the class variable ignored_keys are
    ignored if found in the dictionary created by loadmat. If the key 'D' is found, the
    file will be treated as an SPM MEEG object and the data extracted from the .dat
    file defined within the dictionary.

    If multiple time series are found in the file, the user can specify multi_sequence.
    With its default value 'all', the time series will be concatenated along the time
    axis. Otherwise and integer specifies which time series to read.

    Once instantiated, any property or function which has not been specified for
    Data is provided by the internal numpy.ndarray, time_series. The array can be
    accessed using slice notation on the Data object (e.g. meg_data[:1000, 2:5]
    would return the first 1000 samples and channels 2, 3 and 4. The time axis of the
    array can also be reduced using the data_limits method. This creates an pair of
    internal variables which reduce the length of the data which can be extracted from
    the object without modifying the underlying array.

    A variety of methods are provided for preparing data for analysis. These are
    detailed below.

    Parameters
    ----------
    time_series: numpy.ndarray or str or array-like
        Either an array, array-like object or a string specifying the location of a
        NumPy or MATLAB file.
    sampling_frequency: float
        The sampling frequency of the time_series. The default of 1 means that each
        sample is considered to be a time point (i.e. 1Hz).
    multi_sequence: str or int
        If the time_series provided contains multiple time series, "all" will
        concatenate them while providing an int will specify the corresponding array.

    Methods
    -------


    """

    @auto_repr
    def __init__(
        self,
        time_series: Union[np.ndarray, str, Any],
        sampling_frequency: float = 1,
        multi_sequence: Union[str, int] = "all",
    ):
        self.from_file = time_series if isinstance(time_series, str) else False

        self.time_series, self.sampling_frequency = load_data(
            time_series=time_series,
            multi_sequence=multi_sequence,
            sampling_frequency=sampling_frequency,
        )

        # TODO: Make raw_data read only using @property and self._raw_data
        self.raw_data = np.array(self.time_series)
        self.time_series = self.raw_data.copy()
        self.pca_applied = False

        self.t = None
        if self.time_series.ndim == 2:
            self.t = np.arange(self.time_series.shape[0]) / self.sampling_frequency
            self.time_axis_first()

        self.n_min, self.n_max = None, None

    def __str__(self):
        return_string = [
            f"{self.__class__.__name__}:",
            f"from_file: {self.from_file}",
            f"n_channels: {self.time_series.shape[1]}",
            f"n_time_points: {self.time_series.shape[0]}",
            f"pca_applied: {self.pca_applied}",
            f"data_limits: {self.n_min}, {self.n_max}",
            f"original_shape: {self.raw_data.shape}",
            f"current_shape: {self[:].shape}",
        ]
        return "\n  ".join(return_string)

    def __getitem__(self, val):
        return self.time_series[self.n_min : self.n_max][val]

    def __getattr__(self, attr):
        if attr[:2] == "__":
            raise AttributeError(f"No attribute called {attr}.")
        return getattr(self[:], attr)

    def __array__(self, *args, **kwargs):
        return np.asarray(self[:], *args, **kwargs)

    def data_limits(self, t_min: int = None, t_max: int = None):
        """Set the maximum and minimum sample numbers for the object.

        The underlying time_series remains unchanged.

        Parameters
        ----------
        t_min: int
        t_max: int

        """
        self.n_min = t_min
        self.n_max = t_max

    @property
    def shape(self):
        return self[:].shape

    @property
    def original_shape(self):
        return self.time_series.shape

    def time_axis_first(self):
        """Forces the longer axis of the data to be the first indexed axis.

        """
        self.time_series, transposed = time_axis_first(self.time_series)
        if transposed:
            logging.warning("Assuming time to be the longer axis and transposing.")

    def trim_trials(
        self, trial_start: int = None, trial_cutoff: int = None, trial_skip: int = None,
    ):
        self.time_series = trim_trials(
            epoched_time_series=self.time_series,
            trial_start=trial_start,
            trial_cutoff=trial_cutoff,
            trial_skip=trial_skip,
        )

    def make_continuous(self):
        """Given trial data, return a continuous time series.

        With data input in the form (channels x trials x time), reshape the array to
        create a (time x channels) array. Wraps trials_to_continuous.

        """
        self.time_series = trials_to_continuous(self.time_series)
        self.t = np.arange(self.time_series.shape[0]) / self.sampling_frequency

    def standardize(
        self,
        n_components: Union[float, int] = 0.9,
        pre_scale: bool = True,
        do_pca: Union[bool, str] = True,
        post_scale: bool = True,
    ):
        self.time_series = standardize(
            time_series=self.time_series,
            n_components=n_components,
            pre_scale=pre_scale,
            do_pca=do_pca,
            post_scale=post_scale,
        )

    def scale(self):
        self.time_series = scale(self.time_series)

    def pca(self, n_components: Union[int, float] = 1, force=False):
        if self.pca_applied:
            if not force:
                self.time_series = pca(
                    time_series=self.time_series, n_components=n_components
                )

    def plot(self, n_time_points: int = 10000):
        """Plot time_series.

        """
        plotting.plot_time_series(self.time_series, n_time_points=n_time_points)

    def savemat(self, filename: str, field_name: str = "x"):
        """Save time_series to a .mat file.

        Parameters
        ----------
        filename: str
            The file to save to (with or without .mat extension).
        field_name: str
            The dictionary key (MATLAB object field) which references the data.
        """
        scipy.io.savemat(filename, {field_name: self[:]})

    def save(self, filename: str):
        """Save time_series to a numpy (.npy) file.

        Parameters
        ----------
        filename: str
            The file to save to (with or without .npy extension).
        """
        np.save(filename, self[:])