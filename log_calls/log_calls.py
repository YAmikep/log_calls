__author__ = "Brian O'Neill"  # BTO
__version__ = 'v0.1.10-b2'

"""Decorator that eliminates boilerplate code for debugging by writing
caller name(s) and args+values to stdout or, optionally, to a logger.
NOTE: CPython only -- this uses internals of stack frames
      which may well differ in other interpreters.

Argument logging is based on the Python 2 decorator:
    https://wiki.python.org/moin/PythonDecoratorLibrary#Easy_Dump_of_Function_Arguments
with changes for Py3 and several enhancements, as described in doc/log_calls.md.
"""

import inspect
from functools import wraps, partial
import logging
import sys

#__all__ = ['log_calls', 'difference_update', '__version__', '__author__']


class log_calls():
    """
    This decorator logs the caller of a decorated function, and optionally
    the arguments passed to that function, before calling it; after calling
    the function, it optionally writes the return value (default: it doesn't),
    and optionally prints a 'closing bracket' message (default: it does).
    "logs" means: prints to stdout, or, optionally, to a logger.

    The decorator takes various keyword arguments, all with sensible defaults.
    Every parameter except prefix can take two kinds of values, direct and
    indirect, which you can think of as static and dynamic respectively.
    Direct/static values are actual values used when the decorated function is
    interpreted, e.g. enabled=True, args_sep=" / ". Indirect/dynamic values are
    strings that name keyword arguments of the decorated function; when the
    decorated function is called, the arguments passed by keyword and the
    parameters of the decorated function are searched for the named parameter,
    and if it is found, its value is used. Parameters whose normal type is str
    (args_sep) indicate an indirect value by appending an '='.

    Thus, in:
        @log_calls(args_sep='sep=', prefix="MyClass.")
        def f(a, b, c, sep='|'): pass
    args_sep has an indirect value, and prefix has a direct value. A call can
    dynamically override the default value in the signature of f by supplying
    a value:
        f(1, 2, 3, sep=' $ ')
    or use func's default by omitting the sep argument.

    A decorated function doesn't have to explicitly declare the named parameter,
    if its signature includes **kwargs. Consider:
        @log_calls(enabled='enable')
        def func1(a, b, c, **kwargs): pass
        @log_calls(enabled='enable')
        def func2(z, **kwargs): func1(z, z+1, z+2, **kwargs)
    When the following statement is executed, the calls to both func1 and func2
    will be logged:
        func2(17, enable=True)
    whereas neither of the following two statements will trigger logging:
        func2(42, enable=False)
        func2(99)

    As a concession to consistency, any parameter value that names a keyword
    parameter of the decorated function can also end in a trailing '=', which
    is stripped. Thus, enabled='enable_=' indicates an indirect value supplied
    by the keyword 'enable_' of the decorated function.

        log_args:     arguments passed to the (decorated) function will be logged
                      (Default: True)
        log_retval:   log what the wrapped function returns IFF True/non-false
                      At most MAXLEN_RETVALS chars are printed. (Default: False)
        args_sep:     str used to separate args. The default is  ', ', which lists
                      all args on the same line. If args_sep='\n' is used, then
                      additional spaces are appended to that to make for a neater
                      display. Other separators in which '\n' occurs are left
                      unchanged, and are untested -- experiment/use at your own risk.
                      If args_sep ends in a '=', it's considered to designate
                      the name of a keyword arg of the wrapped function,
                      whose value in turn determines the args_sep to use.
        enabled:      if not a str and 'truthy', then logging will occur.
                      If it's a str, it's considered to designate the name
                      of a keyword arg of the wrapped function, whose value
                      determines whether messages are written or not
                      (truthy <==> they are written). (Default: True)
        prefix:       str to prefix the function name with when it is used
                      in logged messages: on entry, in reporting return value
                      (if log_retval) and on exit (if log_exit). (Default: '')
        log_exit:     If True (the default), the decorator will log an exiting
                      message after calling the function, and before returning
                      what the function returned.
        logger:       If not None (the default), a Logger which will be used
                      to write all messages, or a str naming a keyword arg of
                      the wrapped function; in the last case, the logger used
                      is the value of that arg passed to the function, IF that
                      is a Logger. If no logger is thus obtained, print is used.
        loglevel:     logging level, if logger != None. (Default: logging.DEBUG)
    """
    MAXLEN_RETVALS = 60
    LOG_CALLS_SENTINEL_ATTR = '_log_calls_sentinel_'        # name of attr
    LOG_CALLS_SENTINEL_VAR = "_log_calls-deco'd"
    LOG_CALLS_PREFIXED_NAME = 'log_calls-prefixed-name'     # name of attr

    # When this is last char of a parameter (to log_calls),
    # interpret value of parameter to be the name of
    # a keyword parameter ** of f **
    KEYWORD_MARKER = '='

    def __init__(
            self,
            enabled=True,
            log_args=True,
            log_retval=False,
            log_exit=True,
            args_sep=', ',
            prefix='',
            logger=None,
            loglevel=logging.DEBUG,
    ):
        """(See class docstring)"""
        # Set all except prefix to pairs (is_indirect, val)
        # as returned by analyze_deco_param_value (see its docstring)
        self.enabled = self.analyze_deco_param_value(enabled, int, False)
        self.log_args = self.analyze_deco_param_value(log_args, bool, True)
        self.log_retval = self.analyze_deco_param_value(log_retval, bool, False)
        self.log_exit = self.analyze_deco_param_value(log_exit, bool, True)
        self.args_sep = self.analyze_deco_param_value(args_sep, str, ', ')
        self.prefix = prefix
        self.logger = self.analyze_deco_param_value(logger, logging.Logger, None)
        self.loglevel = self.analyze_deco_param_value(loglevel, int, logging.DEBUG)

    @staticmethod
    def analyze_deco_param_value(val, target_type, default):
        """
        val: passed to __init__,
        target_type: bool int str logger.Logger,
        default: fallback value.
        Return pair (is_indirect, moddedval) where
            is_indirect: bool,
            moddedval = val if kind is direct (not is_indirect),
                      = keyword of wrapped fn if is_indirect
                        (sans any trailing '=')
        """
        # Detect fixup direct/static values, except for target_type == str
        if not isinstance(val, str) or not val:
            indirect = False
            # p not a str, or == '', so use value as-is if valid, else default
            if not isinstance(val, target_type):
                val = default
        else:                           # val is a nonempty str
            if target_type != str:      # val designates a keyword of f
                indirect = True
                # Remove trailing self.KEYWORD_MARKER if any
                if val[-1] == log_calls.KEYWORD_MARKER:
                    val = val[:-1]
            else:                       # target_type == str
                # val denotes an f-keyword IFF last char is KEYWORD_MARKER
                indirect = (val[-1] == log_calls.KEYWORD_MARKER)
                if indirect:
                    val = val[:-1]

        return indirect, val

    def __call__(self, f):
        """Because there are decorator arguments, __call__() is called
        only once, and it can take only a single argument: the function
        to decorate. The return value of __call__ is called subsequently.
        So, this method *returns* the decorator proper."""
        # First, save prefix + function name for function f
        prefixed_fname = self.prefix + f.__name__
        f_params = inspect.signature(f).parameters

        def resolve_deco_param(p, target_type, kwargs, default):
            """
            p: self.<something>,
            target_type: bool int str logger.Logger"""
            indirect, di_val = p    # di_ - direct or indirect
            if not indirect:
                return di_val

            # di_val designates an f-keyword
            if di_val in kwargs:            # actually passed to f
                val = kwargs[di_val]
            elif is_keyword_param(f_params.get(di_val)): # not passed; explicit f-kwd?
                # yes, explicit param of f, so use f's default value
                val = f_params[di_val].default
            else:
                val = default
            # fixup: "loggers" that aren't loggers, "strs" that arent strs, etc
            if val and not isinstance(val, target_type):
                val = default
            return val

        @wraps(f)
        def f_log_calls_wrapper_(*args, **kwargs):

            # # Establish "do_it" - 'enabled'
            # do_it = self.enabled
            # if self.enabled_kwd:
            #     if self.enabled_kwd in kwargs:  # passed to f
            #         do_it = kwargs[self.enabled_kwd]
            #     else:   # not passed; is it an explicit kwd of f?
            #         if is_keyword_param(f_params.get(self.enabled_kwd)):
            #             # yes, explicit param of wrapped f; use f's default value
            #             do_it = f_params[self.enabled_kwd].default
            #         else:
            #             do_it = False

            do_it = resolve_deco_param(self.enabled, int, kwargs, False)
            # if nothing to do, hurry up & don't do it
            if not do_it:
                return f(*args, **kwargs)

            logger = resolve_deco_param(self.logger, logging.Logger, kwargs, None)
            loglevel = resolve_deco_param(self.loglevel, int, kwargs, logging.DEBUG)

            # Establish logging function
            logging_fn = partial(logger.log, loglevel) if logger else print

            # Get list of callers up to & including first log_call's-deco'd fn
            # (or just caller, if no such fn)
            call_list = self.call_chain_to_next_log_calls_fn()

            msg = ("%s <== called by %s"
                   % (prefixed_fname, ' <== '.join(call_list)))
            # Make & append args message
            indent = " " * 4

            log_args = resolve_deco_param(self.log_args, bool, kwargs, True)

            # If function has no parameters, skip arg reportage,
            # don't even bother writing "args: <none>"
            if log_args and f_params:
                argcount = f.__code__.co_argcount
                argnames = f.__code__.co_varnames[:argcount]

                args_sep = resolve_deco_param(self.args_sep, str, kwargs, ', ')
                if not args_sep:
                    args_sep = ', '

                # ~Kludge / incomplete treatment of seps that contain \n
                end_args_line = ''
                if args_sep[-1] == '\n':
                    args_sep = '\n' + (indent * 2)
                    end_args_line = args_sep

                msg += ('\n' + indent + "args: " + end_args_line)

                args_vals = list(zip(argnames, args))
                if args[argcount:]:
                    args_vals.append( ("[*]args", args[argcount:]) )

                explicit_kwargs = {k: v for (k, v) in kwargs.items()
                                   if k in f_params
                                   and is_keyword_param(f_params[k])}
                args_vals.extend( explicit_kwargs.items() )

                implicit_kwargs = difference_update(
                    kwargs.copy(), explicit_kwargs)
                if implicit_kwargs:
                    args_vals.append( ("[**]kwargs",  implicit_kwargs) )

                if args_vals:
                    msg += args_sep.join('%s=%r' % pair for pair in args_vals)
                else:
                    msg += "<none>"

            logging_fn(msg)

            retval = f(*args, **kwargs)

            log_retval = resolve_deco_param(self.log_retval, bool, kwargs, False)

            if log_retval:
                retval_str = str(retval)
                if len(retval_str) > log_calls.MAXLEN_RETVALS:
                    retval_str = retval_str[:log_calls.MAXLEN_RETVALS] + "..."
                logging_fn(indent + "%s return value: %s"
                           % (prefixed_fname, retval_str))

            log_exit = resolve_deco_param(self.log_exit, bool, kwargs, True)
            if log_exit:
                logging_fn("%s ==> returning to %s"
                           % (prefixed_fname, ' ==> '.join(call_list)))
            return retval

        # Add a sentinel as a property to f_log_calls_wrapper_
        # so we can in theory chase back to any previous log_calls-decorated fn
        setattr(
            f_log_calls_wrapper_,
            self.LOG_CALLS_SENTINEL_ATTR,
            self.LOG_CALLS_SENTINEL_VAR
        )
        setattr(
            f,
            self.LOG_CALLS_PREFIXED_NAME,
            prefixed_fname
        )

        return f_log_calls_wrapper_

    @staticmethod
    def call_chain_to_next_log_calls_fn():
        """Return list of callers (names) on the call chain
        from caller of caller to first log_calls-deco'd function inclusive,
        if any.  If there's no log_calls-deco'd function on the stack,
        or anyway if none are discernible, return [caller_of_caller]."""
        curr_frame = sys._getframe(2)   # caller-of-caller's frame
        found = False
        call_list = []
        while curr_frame:
            curr_funcname = curr_frame.f_code.co_name
            if curr_funcname == 'f_log_calls_wrapper_':
                # Previous was decorated inner fn; don't add 'f_log_calls_wrapper_'
                # print("**** found f_log_calls_wrapper_, prev fn name =", call_list[-1])     # <<<DEBUG>>>
                # Fixup: get prefixed named of wrapped function
                call_list[-1] = getattr(curr_frame.f_locals['f'],
                                        log_calls.LOG_CALLS_PREFIXED_NAME)
                found = True
                break
            call_list.append(curr_funcname)
            if curr_funcname == '<module>':
                break

            globs = curr_frame.f_back.f_globals
            curr_fn = None
            if curr_funcname in globs:
                curr_fn = globs[curr_funcname]
            # If curr_funcname is a decorated inner function,
            # then it's not in globs. If it's called from outside
            # it's enclosing function, it's caller is 'f_log_calls_wrapper_'
            # so we'll see that on next iteration.
            else:
                try:
                    # if it's a decorated inner function that's called
                    # by its enclosing function, detect that:
                    locls = curr_frame.f_back.f_back.f_locals
                    if curr_funcname in locls:
                        curr_fn = locls[curr_funcname]
                        #   print("**** %s found in locls = curr_frame.f_back.f_back.f_locals, "
                        #         "curr_frame.f_back.f_back.f_code.co_name = %s"
                        #         % (curr_funcname, curr_frame.f_back.f_back.f_locals)) # <<<DEBUG>>>
                except AttributeError:
                    # print("**** %s not found (inner fn?)" % curr_funcname)       # <<<DEBUG>>>
                    pass

            if hasattr(curr_fn, log_calls.LOG_CALLS_SENTINEL_ATTR):
                found = True
                break
            curr_frame = curr_frame.f_back

        # So:
        # If found, then call_list[-1] is log_calls-wrapped;
        # if not found, truncate call_list to first element.
        if not found:
            call_list = call_list[:1]

        return call_list


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# helpers
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def is_keyword_param(param):
    return param and (
        param.kind == param.KEYWORD_ONLY
        or
        ((param.kind == param.POSITIONAL_OR_KEYWORD)
         and param.default is not param.empty)
    )


def difference_update(d, d_remove):
    """Change and return d.
    d: mutable mapping, d_remove: iterable.
    There is such a method for sets, but unfortunately not for dicts."""
    for k in d_remove:
        if k in d:
            del(d[k])
    return d    # so that we can pass a call to this fn as an arg, or chain
