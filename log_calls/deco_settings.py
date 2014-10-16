__author__ = "Brian O'Neill"  # BTO
__version__ = 'v0.1.10-b4'
__doc__ = """
DecoSettingsMapping -- class that's usable with any class-based decorator
that has several keyword parameters; this class makes it possible for
a user to access the collection of settings as an attribute
(object of type DecoSettingsMapping) of the decorated function.
The attribute/obj of type DecoSettingsMapping provides
    (*) a mapping interface for the decorator's keyword params
    (*) an attribute interface for its keyword params
        i.e. attributes of the same names,
    as well as 'direct' and 'indirect' values for its keyword params
    q.v.
Using this class, any setting under its management can take two kinds of values:
direct and indirect, which you can think of as static and dynamic respectively.
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
"""

from .helpers import is_keyword_param
import pprint


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# classes
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DecoSetting():
    """a little struct - static info about one setting (keyword parameter),
                         sans any value. """
    def __init__(self, name, final_type, default, *, allow_falsy, allow_indirect):
        assert not default or isinstance(default, final_type)
        self.name = name                # key
        self.final_type = final_type    # bool int str logging.Logger ...
        self.default = default
        self.allow_falsy = allow_falsy  # is a falsy final val of setting allowed
        self.allow_indirect = allow_indirect  # are indirect values allowed

    def __repr__(self):
        final_type = repr(self.final_type)[8:-2]     # E.g. <class 'int'>  -->  int
        default = self.default if final_type != str else repr(self.default)
        return ("DecoSetting(%s, %s, %r, allow_falsy=%s, allow_indirect=%s)"
                %
                (self.name, final_type, default, self.allow_falsy, self.allow_indirect)
        )


class DecoSettingsMapping():
    """Usable with any class-based decorator that wants to implement
    a mapping interface and attribute interface for its keyword params,
    as well as 'direct' and 'indirect' values for its keyword params"""
    _classname2SettingsData_dict = {}

    # When this is last char of a parameter value (to decorator),
    # interpret value of parameter to be the name of
    # a keyword parameter ** of the wrapped function f **
    KEYWORD_MARKER = '='

    @classmethod
    def register_class_settings(cls, classname, settings_iter):
        """
        Client class should call this *** from class level ***
        e.g.
            DecoSettingsMapping.register_class_settings('log_calls', _setting_info_list)

        Add item (classname, d) to _classname2SettingsData_dict
        where d is a dict built from items of settings_iter.
        cls: this class
        clsname: key for dict produced from settings_iter
        settings_iter: iterable of Keyed"""
        d = {}
        for setting in settings_iter:
            d[setting.name] = setting

        cls._classname2SettingsData_dict[classname] = d

        # <<<attributes>>> Set up descriptors
        for name in d:
            setattr(cls, name, cls.make_descriptor(name))

    # <<<attributes>>>
    @staticmethod
    def make_descriptor(name):
        class Descr():
            """A little data descriptor which just delegates
            to __getitem__ and __setitem__ of instance"""
            def __get__(self, instance, owner):
                """
                instance: a DecoSettingsMapping
                owner: class DecoSettingsMapping(?)"""
                return instance[name]

            def __set__(self, instance, value):
                """
                instance: a DecoSettingsMapping
                value: what to set"""
                # ONLY do this is name is a legit setting name
                # (for this obj, as per this obj's initialization)
                instance[name] = value

        return Descr()

    def get_settings_for_class(self):
        return self._classname2SettingsData_dict[self.classname]

    def __init__(self, classname, **values_dict):
        """classname: name of class that has already stored its settings
        by calling register_class_settings(cls, classname, settings_iter)

        values_iterable: iterable of pairs
                       (name,
                        value such as is passed to log_calls-__init__)
                        values are either 'direct' or 'indirect'

        Assumption: every name in values_iterable is info.name
                    for some info in settings_info.
        Must be called after __init__ sets self.classname."""
        self.classname = classname
        class_settings_dict = self.get_settings_for_class()

        self._tagged_values_dict = {}    # stores pairs inserted by __setitem__

        for k, v in values_dict.items():
            self.__setitem__(k, v, class_settings_dict_=class_settings_dict)

    def __setitem__(self, key, value, class_settings_dict_=None):
        """
        key: name of setting, e.g. 'prefix';
             must be in self.get_settings_for_class()
        value: something passed to __init__ (of log_calls),
        class_settings_dict_: passed by __init__ or any other method that will
                              call many times, saves this method from having
                              to do self.get_settings_for_class() on each call
        Return pair (is_indirect, modded_val) where
            is_indirect: bool,
            modded_val = val if kind is direct (not is_indirect),
                       = keyword of wrapped fn if is_indirect
                         (sans any trailing '=')
        THIS method assumes that the values in self.get_settings_for_class()
        are DecoSetting objects -- all fields of that class are used
        """
        class_settings_dict = class_settings_dict_ or self.get_settings_for_class()
        if key not in class_settings_dict:
            raise KeyError(
                "DecoSettingsMapping.__setitem__: KeyError - no such setting (key) as '%s'" % key)

        info = class_settings_dict[key]
        final_type = info.final_type
        default = info.default
        allow_falsy = info.default
        allow_indirect = info.allow_indirect

        if not allow_indirect:
            self._tagged_values_dict[key] = False, value
            return

        # Detect fixup direct/static values, except for final_type == str
        if not isinstance(value, str) or not value:
            indirect = False
            # value not a str, or == '', so use value as-is if valid, else default
            if (not value and not allow_falsy) or not isinstance(value, final_type):
                value = default
        else:                           # val is a nonempty str
            if final_type != str:       # val designates a keyword of f
                indirect = True
                # Remove trailing self.KEYWORD_MARKER if any
                if value[-1] == self.KEYWORD_MARKER:
                    value = value[:-1]
            else:                       # final_type == str
                # val denotes an f-keyword IFF last char is KEYWORD_MARKER
                indirect = (value[-1] == self.KEYWORD_MARKER)
                if indirect:
                    value = value[:-1]

        self._tagged_values_dict[key] = indirect, value

    def __getitem__(self, key):
        indirect, value = self._tagged_values_dict[key]
        if indirect:
            return value + '='
        else:
            return value

    def __len__(self):
        return len(self._tagged_values_dict)

    def __iter__(self):
        return (name for name in self._tagged_values_dict)

    def items(self):
        return ((name, self.__getitem__(name)) for name in self._tagged_values_dict)

    def __contains__(self, key):
        return key in self._tagged_values_dict

    def __repr__(self):
        class_settings_dict = self.get_settings_for_class()

        list_of_settingsinfo_reprs = []

        for k, info in class_settings_dict.items():
            list_of_settingsinfo_reprs.append(repr(info))

        def multiline(lst):
            return '    [\n        ' + \
                   ',\n        '.join(lst) + \
                   '\n    ]'

        return "DecoSettingsMapping( \n" \
               "%s, \n" \
               "    %s\n" \
               ")" % \
               (multiline(list_of_settingsinfo_reprs),
                pprint.pformat(self.as_dict(), indent=8)
               )

    def __str__(self):
        return str(self.as_dict())

    def update(self, **d_settings):
        for k, v in d_settings.items():
            self.__setitem__(k, v)      # i.e. self[k] = v ?!

    def as_dict(self):
        d = {}
        for name in self._tagged_values_dict:
            d[name] = self.__getitem__(name)  # self[name] ?!
        return d

    def _get_tagged_value(self, key):
        """Return (indirect, value) for key"""
        return self._tagged_values_dict[key]

    def get_final_value(self, name, fparams, kwargs):
        """
        name:    key into self._tagged_values_dict, self._setting_info_list
        fparams: inspect.signature(f).parameters of some function f
        kwargs:  kwargs of a call to that function f
        THIS method assumes that the objs stored in self.get_settings_for_class()
        are DecoSetting objects -- this method uses every attribute of that class
                                   except allow_indirect.
        """
        indirect, di_val = self._tagged_values_dict[name]  # di_ - direct or indirect
        if not indirect:
            return di_val

        setting_info = self.get_settings_for_class()[name]
        final_type = setting_info.final_type
        default = setting_info.default
        allow_falsy = setting_info.default

        # di_val designates a (potential) f-keyword
        if di_val in kwargs:            # actually passed to f
            val = kwargs[di_val]
        elif is_keyword_param(fparams.get(di_val)): # not passed; explicit f-kwd?
            # yes, explicit param of f, so use f's default value
            val = fparams[di_val].default
        else:
            val = default
        # fixup: "loggers" that aren't loggers, "strs" that arent strs, etc
        if (not val and not allow_falsy) or (val and not isinstance(val, final_type)):
            val = default
        return val