from setuptools import setup, Extension
import pybind11

#define the C++ extension module
ext_modules = [
    Extension(
        "todo_core",
        ["matcher.cpp"],
        include_dirs=[pybind11.get_include()],
        language='c++',
        extra_compile_args=['-std=c++11'], #ensure C++11 standard
    ),
]

setup(
    name="todo_core",
    version="0.1",
    author="Zhou Zihao",
    description="A C++ backend engine for TodoList with vector search",
    ext_modules=ext_modules,
)