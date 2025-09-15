from setuptools import setup, find_packages

setup(
    name="hardbound",
    version="2.0.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "hardbound=hardbound:main",
        ],
    },
    python_requires=">=3.13",
    install_requires=[],
    extras_require={
        "progress": ["tqdm"],
    },
)
