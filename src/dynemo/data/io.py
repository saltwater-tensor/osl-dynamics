import logging
import pathlib
import pickle
from os import listdir, path
from shutil import rmtree
from typing import Tuple, Union

import mat73
import numpy as np
import scipy.io
from tqdm import tqdm
from dynemo.data import spm

_logger = logging.getLogger("DyNeMo")


class IO:
    """Class for reading/writing data.

    Parameters
    ----------
    inputs : list of str or str
        Filenames to be read.
    data_field : str
        If a MATLAB filename is passed, this is the field that corresponds to the
        data. Optional. By default we read the field 'X'.
    sampling_frequency : float
        Sampling frequency of the data in Hz. Optional.
    store_dir : str
        Directory to save results and intermediate steps to. Optional, default is /tmp.
    time_axis_first : bool
        Is the input data of shape (n_samples, n_channels)?
    keep_memmaps_on_close : bool
        Should we keep the memmaps? Optional, default is False.
    """

    def __init__(
        self,
        inputs: Union[list, str, np.ndarray],
        data_field: str,
        sampling_frequency: float,
        store_dir: str,
        time_axis_first: bool,
        keep_memmaps_on_close: bool = False,
    ):
        # Validate inputs
        if isinstance(inputs, str):
            if path.isdir(inputs):
                self.inputs = list_dir(inputs, keep_ext=[".npy", ".mat"])
            else:
                self.inputs = [inputs]

        elif isinstance(inputs, np.ndarray):
            if inputs.ndim == 2:
                self.inputs = [inputs]
            else:
                self.inputs = inputs

        elif isinstance(inputs, list):
            if len(inputs) == 0:
                raise ValueError("Empty list passed.")
            elif isinstance(inputs[0], str):
                self.inputs = []
                for inp in inputs:
                    if path.isdir(inp):
                        self.inputs += list_dir(inp, keep_ext=[".npy", ".mat"])
                    else:
                        self.inputs.append(inp)
            else:
                self.inputs = inputs

        else:
            raise ValueError("inputs must be str, np.ndarray or list.")

        if len(self.inputs) == 0:
            raise ValueError("No valid inputs were passed.")

        self.keep_memmaps_on_close = keep_memmaps_on_close

        # Directory to store memory maps created by this class
        self.store_dir = pathlib.Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

        # Load and validate the raw data
        self.raw_data_memmaps, self.raw_data_filenames = self.load_raw_data(
            data_field, time_axis_first
        )
        self.validate_data()

        # Get data prepration attributes if the raw data has been prepared
        if not isinstance(inputs, list):
            self.load_preparation(inputs)

        # Attributes describing the raw data
        self.n_raw_data_channels = self.raw_data_memmaps[0].shape[-1]
        self.sampling_frequency = sampling_frequency

        # Use raw data for the subject data
        self.subjects = self.raw_data_memmaps

    def delete_dir(self):
        """Deletes store_dir."""
        if self.store_dir.exists():
            rmtree(self.store_dir)

    def delete_io_memmaps(self):
        """Deletes memmaps and removes store_dir if empty."""
        if self.raw_data_filenames is not None:
            for filename in self.raw_data_filenames:
                pathlib.Path(filename).unlink(missing_ok=True)
        if self.store_dir.exists():
            if not any(self.store_dir.iterdir()):
                self.store_dir.rmdir()
        self.raw_data_memmaps = None
        self.raw_data_filenames = None

    def load_preparation(self, inputs: str):
        """Loads a pickle file containing preparation settings.

        Parameters
        ----------
        inputs : str
            Path to directory containing the pickle file with preparation settings.
        """
        if path.isdir(inputs):
            for file in list_dir(inputs):
                if "preparation.pkl" in file:
                    preparation = pickle.load(open(inputs + "/preparation.pkl", "rb"))
                    self.n_embeddings = preparation["n_embeddings"]
                    self.pca_components = preparation["pca_components"]
                    self.n_pca_components = preparation["pca_components"].shape[1]
                    self.prepared = True

    def load_raw_data(
        self, data_field: str, time_axis_first: bool
    ) -> Tuple[list, list]:
        """Import data into a list of memory maps.

        Parameters
        ----------
        data_field : str
            If a MATLAB filename is passed, this is the field that corresponds
            to the data. By default we read the field 'X'.
        time_axis_first : bool
            Is the input data of shape (n_samples, n_channels)?

        Returns
        -------
        list
            list of np.memmap.
        """
        raw_data_pattern = "raw_data_{{i:0{width}d}}_{identifier}.npy".format(
            width=len(str(len(self.inputs))), identifier=self._identifier
        )
        raw_data_filenames = [
            str(self.store_dir / raw_data_pattern.format(i=i))
            for i in range(len(self.inputs))
        ]
        # self.raw_data_filenames is not used if self.inputs is a list of strings,
        # where the strings are paths to .npy files

        memmaps = []
        for raw_data, mmap_location in zip(
            tqdm(self.inputs, desc="Loading files", ncols=98), raw_data_filenames
        ):
            raw_data_mmap = load_data(
                raw_data, data_field, mmap_location, mmap_mode="r"
            )
            if not time_axis_first:
                raw_data_mmap = raw_data_mmap.T
            memmaps.append(raw_data_mmap)

        return memmaps, raw_data_filenames

    def save(self, output_dir: str = "."):
        """Saves data to numpy files.

        Parameters
        ----------
        output_dir : str
            Path to save data files to. Optional, default is the current working
            directory.
        """
        output_dir = pathlib.Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save time series data
        for i in tqdm(range(self.n_subjects), desc="Saving data", ncols=98):
            np.save(f"{output_dir}/subject{i}.npy", self.subjects[i])

        # Save preparation info if .prepared has been called
        if self.prepared:
            preparation = {
                "n_embeddings": self.n_embeddings,
                "pca_components": self.pca_components,
            }
            pickle.dump(preparation, open(f"{output_dir}/preparation.pkl", "wb"))

    def validate_data(self):
        """Validate data files."""
        n_channels = [memmap.shape[-1] for memmap in self.raw_data_memmaps]
        if not np.equal(n_channels, n_channels[0]).all():
            raise ValueError("All inputs should have the same number of channels.")


def file_ext(filename: str) -> str:
    """Returns the extension of a file.

    Parameters
    ----------
    filename : str
        Path to file.
    """
    if not isinstance(filename, str):
        return None
    _, ext = path.splitext(filename)
    return ext


def list_dir(path: str, keep_ext: Union[str, list] = None) -> list:
    """Lists a directory.

    Parameters
    ----------
    path : str
        Directory to list.
    keep_ext : str or list
        Extensions of files to include in the returned list. Optional, default
        is to include add files.

    Returns
    -------
    list
        Full path to files with the correct extension.
    """
    files = []
    if keep_ext is None:
        for file in sorted(listdir(path)):
            files.append(path + "/" + file)
    else:
        if isinstance(keep_ext, str):
            keep_ext = [keep_ext]
        for file in sorted(listdir(path)):
            if file_ext(file) in keep_ext:
                files.append(path + "/" + file)
    return files


def load_data(
    data: Union[str, list, np.ndarray],
    data_field: str = "X",
    mmap_location: str = None,
    mmap_mode: str = "r+",
) -> Union[np.ndarray, np.memmap]:
    """Loads time series data.

    Checks the data shape is time by channel and that the data is float32.

    Parameters
    ----------
    data : numpy.ndarray or str or list
        An array or filename of a .npy or .mat file containing the data.
    data_field : str
        If a MATLAB filename is passed, this is the field that corresponds to
        the data.
    mmap_location : str
        Filename to save the data as a numpy memory map.
    mmap_mode : str
        Mode to load memory maps in. Optional, default is 'r+'.

    Returns
    -------
    np.memmap or np.ndarray
        Data.
    """
    if isinstance(data, np.ndarray):
        data = data.astype(np.float32)
        if mmap_location is None:
            return data
        else:
            # Save to a file so we can load data as a memory map
            np.save(mmap_location, data)
            data = mmap_location

    if isinstance(data, str):
        # Check if file/folder exists
        if not path.exists(data):
            raise FileNotFoundError(data)

        # Check extension
        ext = file_ext(data)
        if ext not in [".npy", ".mat"]:
            raise ValueError("Data file must be .npy or .mat.")

        # Load a MATLAB file
        if ext == ".mat":
            data = load_matlab(data, data_field)
            data = data.astype(np.float32)
            if mmap_location is None:
                return data
            else:
                # Save to a file so we can load data as a memory map
                np.save(mmap_location, data)
                data = mmap_location

        # Load a numpy file
        elif ext == ".npy":
            if mmap_location is None:
                data = np.load(data)
                data = data.astype(np.float32)
                return data
            else:
                mmap_location = data

    # Load data as memmap
    data = np.load(mmap_location, mmap_mode=mmap_mode)

    return data


def load_matlab(filename: str, field: str, ignored_keys=None) -> np.ndarray:
    """Loads a MATLAB or SPM file.

    Parameters
    ----------
    filename : str
        Filename of MATLAB file to read.
    field : str
        Field that corresponds to the data.
    ignored_keys :  list of str
        Keys in the MATLAB file to ignore.

    Returns
    -------
    np.ndarray
        Data in the MATLAB/SPM file.
    """
    # Load file
    mat = loadmat(filename, return_dict=True)

    # Get data
    if "D" in mat:
        _logger.warning("Assuming that key 'D' corresponds to an SPM MEEG object.")
        D = spm.SPM(filename)
        data = D.data
    else:
        try:
            data = mat[field]
        except KeyError:
            raise KeyError(f"field '{field}' missing from MATLAB file.")

    return data


def loadmat(filename: str, return_dict: bool = False) -> Union[dict, np.ndarray]:
    """Wrapper for scipy.io.loadmat or mat73.loadmat.

    Parameters
    ----------
    filename : str
        Filename of MATLAB file to read.
    return_dict : bool
        If there's only one field should we return a dictionary. Optional.
        Default is to return a numpy array if there is only one field.
        If there are multiple fields, a dictionary is always returned.

    Returns
    -------
    dict or np.ndarray
        Data in the MATLAB file.
    """
    try:
        mat = scipy.io.loadmat(filename, simplify_cells=True)
    except NotImplementedError:
        mat = mat73.loadmat(filename)

    if not return_dict:
        # Check if there's only one key in the MATLAB file
        fields = [field for field in mat if "__" not in field]
        if len(fields) == 1:
            mat = mat[fields[0]]

    return mat