from typing import Callable, Any, Optional, List, ClassVar, Union
from enum import Enum
import sys, inspect, dataclasses, typing_inspect


def _process_load_as(clazz, source_type: type, field_name: str):
    def load_as_impl():
        return source_type

    def loader(value):
        s = clazz(**{ field_name : value })
        return s

    setattr(clazz, '__load_as__', load_as_impl)
    setattr(clazz, '__load_as_loader__', loader)
    return clazz


def inline_loader(_cls: type = None, *, source_type: type, field_name: str):

    def wrap(cls):
        return _process_load_as(cls, source_type, field_name)

    if _cls is None:
        return wrap

    return wrap(_cls)


def is_inline_loaded(obj):
    clazz = obj if isinstance(obj, type) else type(obj)
    return hasattr(clazz, '__load_as__')


def get_inline_load_type(obj):
    @dataclasses.dataclass
    class _InlineLoadType:
        inline_type: type
        loader: Callable[[str], Any] = None

    if not is_inline_loaded(obj):
        raise TypeError(f"Type '{type(obj)}' doesn't have @inline_loader decorator!")
    return _InlineLoadType(
        inline_type=obj.__load_as__(),
        loader=obj.__load_as_loader__
    )


##########################################################################


class EErrorFormat(Enum):
    Pretty = 1
    MSVC = 2


@dataclasses.dataclass
class Source:
    line_number: int
    column_number: int
    buffer: str
    file_name: str

    def format(self, label:str, message:str, error_format:EErrorFormat):
        src_prefix = '>  '
        src_margin_top = 1
        src_margin_bottom = 1

        newline = '\n'
        newline_pretty = f'\n{src_prefix}'

        # Find length of last line
        last_line_idx = self.buffer.rfind('\n')
        last_line_len = (len(self.buffer) - last_line_idx if last_line_idx != -1 else len(self.buffer)) - self.column_number - 2

        src_lines = (self.buffer).replace(newline, newline_pretty)

        main_line = ''
        pointer = ''

        if error_format == EErrorFormat.MSVC:
            main_line = self.format_line_msvc(label, message)
            pointer = self._format_ptr_msvc(src_prefix, last_line_len, newline)
        elif error_format == EErrorFormat.Pretty:
            main_line = self.format_line_pretty(label, message)
            pointer = self._format_ptr_pretty(src_prefix, last_line_len, newline)
        else:
            return ValueError(f"Unknown EErrorFormat value '{error_format}'")

        return (
            f'{main_line}'
            f'{newline_pretty * src_margin_top}\n'
            f'{src_prefix}{src_lines}\n'
            f'{pointer}'
            f'{newline_pretty * src_margin_bottom}'
        )

    def _format_ptr_msvc(self, src_prefix:str, last_line_len:int, newline:str):
        return (
            f'{src_prefix}{"":>{self.column_number}}^{newline}'
            f'{src_prefix}{"":>{self.column_number}}|{newline}'
            f'{src_prefix}{"":>{self.column_number}}+-(line: {self.line_number})'
        )

    def _format_ptr_pretty(self, src_prefix:str, last_line_len:int, newline:str):
        return (
            f'{src_prefix}{"":>{self.column_number}}┬{"─"*last_line_len}{newline}'
            f'{src_prefix}{"":>{self.column_number}}└─(line: {self.line_number})'
        )

    def format_line(self, label:str, message:str, error_format:EErrorFormat):
        if error_format == EErrorFormat.MSVC:
            return self.format_line_msvc(label, message)
        elif error_format == EErrorFormat.Pretty:
            return self.format_line_pretty(label, message)
        else:
            return ValueError(f"Unknown EErrorFormat value '{error_format}'")

    def format_line_msvc(self, label:str, message:str):
        first_line = ''
        if len(label) != 0:
            first_line = f'{label} : {message}'
        else:
            first_line = f'{message}'

        return (f'{self.file_name}({self.line_number},{self.column_number}) : {first_line}')

    def format_line_pretty(self, label:str, message:str):
        first_line = ''
        if len(label) != 0:
            first_line = f'{label}: {message}'
        else:
            first_line = f'{message}'

        return (
            f'{first_line}\n'
            f'in "{self.file_name}", line {self.line_number}, column {self.column_number}:'
        )


@dataclasses.dataclass
class DataclassErrorMessage:
    source: Source
    label: str
    message: str
    error_format: EErrorFormat


class DataclassLoadError(Exception):
    LABEL:ClassVar[str] = 'error'
    error_msg: DataclassErrorMessage
    msg:str = ''
    source:Source = None
    format:EErrorFormat = EErrorFormat.Pretty

    errors: List[Union[Exception,DataclassErrorMessage]] = []

    def is_compound(self):
        return len(self.errors) > 0

    def has_data_errors(self):
        return any(isinstance(e, DataclassErrorMessage) for e in self.errors)

    @staticmethod
    def from_exception_list(msg:str, src:Source, excs:List[Exception], format:EErrorFormat = EErrorFormat.Pretty):
        result = DataclassLoadError()
        result.errors = []

        def build_errors_recursive(ex):
            if isinstance(ex, DataclassLoadError):
                if ex.msg != '':
                    result.errors.append(DataclassErrorMessage(
                        source=ex.source,
                        label=ex.LABEL,
                        message=ex.msg,
                        error_format=format
                    ))
                if ex.is_compound():
                    for sub_ex in ex.errors:
                        build_errors_recursive(sub_ex)
            else:
                result.errors.append(ex)

        for ex in excs:
            build_errors_recursive(ex)

        result.msg = msg
        result.source = src
        result.format = format
        return result

    @staticmethod
    def from_error_list(src:Source, errs:List[DataclassErrorMessage], format:EErrorFormat = EErrorFormat.Pretty):
        result = DataclassLoadError()
        result.errors = errs
        result.source = src
        result.format = format
        return result

    @staticmethod
    def from_source(msg:str, src:Source, format:EErrorFormat = EErrorFormat.Pretty):
        result = DataclassLoadError()
        result.errors = []
        result.msg = msg
        result.source = src
        result.format = format
        return result

    def __init__(self):
        pass

    def __str__(self):
        def print_err(err):
            if isinstance(err, DataclassErrorMessage):
                if hasattr(err, 'errors'):
                    mid_buff = []
                    for sub_err in err.errors:
                        mid_buff.append(print_err(sub_err))
                    return '\n'.join(mid_buff)
                elif err.source is not None:
                    return err.source.format(err.label, err.message, self.format)
                else:
                    return f"{err.label}: {err.message}"
            else:
                return str(err)

        if self.is_compound():
            buffer = [ f"{self.LABEL} : {self.msg}" ] if self.msg != '' and self.msg != None else []
            buffer.append('')
            for err in self.errors:
                buffer.append(print_err(err))
            return '\n'.join(buffer)
        else:
            return self.source.format(self.LABEL, self.msg, self.format)


class UnhandledType(Exception):
    pass


class SourceTracker:
    __source_map__ = dict()
    __root_src__: Source

    def __init__(self, src: Source):
        self.__root_src__ = src
        self.__source_map__ = dict()

    @staticmethod
    def build_code_snippet(get_line:Callable[[int],str], start_line:int, snippet_lines:int):
        snippet = []
        for i in range(min(snippet_lines, start_line), 0, -1):
            snippet.append(get_line(start_line - i))
        return snippet

    def track_field(self, field_name: str, src: Source):
        self.__source_map__[field_name] = src

    def format_source(self):
        return self.__root_src__.format()

    def format_field_source(self, fieldname:str):
        field_src : Source = self.get_field_source(fieldname)
        if field_src is not None:
            return field_src.format()
        return ""

    def get_source(self):
        return self.__root_src__

    def get_field_source(self, field_name:str):
        if field_name in self.__source_map__:
            return self.__source_map__[field_name]
        return None


_LOADED_FROM_FILE_ATTR = '__loaded_from_file__'
_SOURCE_TRACKED_ATTR = '__source_tracker__'


def is_loaded_from_file(obj):
    clazz = obj if isinstance(obj, type) else type(obj)
    return hasattr(clazz, _LOADED_FROM_FILE_ATTR)


def is_source_tracked(obj):
    clazz = obj if isinstance(obj, type) else type(obj)
    return hasattr(clazz, _SOURCE_TRACKED_ATTR)


def loaded_from_file(clazz):
    def set_loaded_from_file(self, path : str):
        setattr(self, _LOADED_FROM_FILE_ATTR, path)

    def get_loaded_from_file(self):
        return getattr(self, _LOADED_FROM_FILE_ATTR)

    setattr(clazz, _LOADED_FROM_FILE_ATTR, None)
    setattr(clazz, 'set_loaded_from_file', set_loaded_from_file)
    setattr(clazz, 'get_loaded_from_file', get_loaded_from_file)
    return clazz


def track_source(clazz):
    def set_source_tracker(self, tracker: SourceTracker):
        self.__source_tracker__ = tracker

    def get_root_source(self):
        return self.__source_tracker__.__root_src__

    def get_field_source(self, field_name: str) -> Optional[Source]:
        return self.__source_tracker__.get_field_source(field_name)

    def format_source(src: Source, label:str, msg:str, error_format:EErrorFormat):
        return src.format(label, msg, error_format)

    def format_message(self, label:str, msg:str, error_format:EErrorFormat):
        return format_source(self.get_root_source(), label, msg, error_format)

    def format_field_message(self, field_name: str, label:str, msg:str, error_format:EErrorFormat):
        src = self.get_field_source(field_name)
        if src is not None:
            return format_source(src, label, msg, error_format)
        return ""

    setattr(clazz, _SOURCE_TRACKED_ATTR, None)
    setattr(clazz, "set_source_tracker", set_source_tracker)
    setattr(clazz, "get_root_source", get_root_source)
    setattr(clazz, "get_field_source", get_field_source)
    setattr(clazz, "format_message", format_message)
    setattr(clazz, "format_field_message", format_field_message)
    return clazz


##########################################################################


def is_clazz_list(clazz):
    if clazz is list:
        return True

    return typing_inspect.get_origin(clazz) == list


def is_clazz_dict(clazz):
    if clazz is dict:
        return True

    return typing_inspect.get_origin(clazz) == dict


def get_type_name(clazz):
    module = clazz.__module__
    if module == 'builtins':
        return clazz.__qualname__
    return module + '.' + clazz.__qualname__


def get_types_from_modules(modules: List[str]):
    result = set()
    for m in modules:
        result.update(set(get_types_from_module(m)))
    return list(result)


def get_types_from_module(modulename : str):
    result = []
    for _, obj in inspect.getmembers(sys.modules[modulename]):
        if inspect.isclass(obj):
            result.append(obj)
    return result


def print_dataclass(clazz, indent=0):
    prefix = ''
    for i in range(indent):
        prefix += ' '

    if dataclasses.is_dataclass(clazz):
        print(f'{prefix}Class: {clazz.__name__}')
        for field in dataclasses.fields(clazz):
            print(f'{prefix}name: {field.name}, type: {field.type}')
            print_dataclass(field.type, indent + 4)
    else:
        if typing_inspect.is_generic_type(clazz):
            if typing_inspect.get_origin(clazz) == list:
                subtype = clazz.__args__[0]
                print(f'{prefix}subtype: {subtype}')
                print_dataclass(subtype, indent + 4)
            else:
                print(f'{prefix }Unhandled type {clazz}')
