from setuptools import setup

setup(
    name="env-verify",
    version="0.0.1",
    py_modules=["env_verify"],
    entry_points={
        "console_scripts": [
            "env-verify=env_verify:main",
        ],
    },
)
