import logging
from functools import wraps
from time import time


def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        print(f"{f.__name__!r} took: {te - ts:2.4f} sec")
        return result

    return wrap


def doublewrap(f):
    """
    a decorator decorator, allowing the decorator to be used as:
    @decorator(with, arguments, and=kwargs)
    or
    @decorator
    """

    @wraps(f)
    def new_dec(*args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # actual decorated function
            return f(args[0])
        else:
            # decorator arguments
            return lambda realf: f(realf, *args, **kwargs)

    return new_dec


@doublewrap
def transpose(f, *arguments):
    try:
        iter(arguments)
    except TypeError:
        arguments = [arguments]
    finally:
        positional_arguments = [a for a in arguments if isinstance(a, int)]
        keyword_arguments = [a for a in arguments if isinstance(a, str)]

    @wraps(f)
    def wrap(*args, **kwargs):
        args = [*args]
        for i in positional_arguments:
            try:
                if args[i].shape[1] > args[i].shape[0]:
                    args[i] = args[i].T
                    logging.warning(
                        f"Argument {i}: assuming longer axis to be time and transposing."
                    )
            except IndexError:
                logging.debug(f"Positional argument {i} not in args.")
        for k in keyword_arguments:
            try:
                if kwargs[k].shape[1] > kwargs[k].shape[0]:
                    kwargs[k] = kwargs[k].T
            except KeyError:
                logging.debug(f"Argument {k} not found in kwargs.")

        return f(*args, **kwargs)

    return wrap
