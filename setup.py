from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="hermes-cli",
    version="0.1.0",
    description="Advanced CLI tool for Google Workspace services and Gemini AI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="NSakthivel",
    author_email="nsakthiveldev@gmail.com",
    url="https://github.com/nsakthivel/Hermes-CLI",
    packages=find_packages(exclude=["tests*", "dist*", "build*"]),
    install_requires=[
        "click>=8.0.0",
        "google-auth>=2.0.0",
        "google-auth-oauthlib>=1.0.0",
        "google-auth-httplib2>=0.1.0",
        "google-api-python-client>=2.0.0",
        "tabulate>=0.9.0",
        "colorama>=0.4.4",
        "diskcache>=5.4.0",
        "prompt-toolkit>=3.0.0",
        "pyyaml>=6.0",
        "python-dateutil>=2.8.0",
        "requests>=2.25.0",
        "google-genai>=0.1.0",
        "google-generativeai>=0.3.0",
        "plyer>=2.1.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "build>=1.0.0",
            "twine>=4.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "hermes=gsuite_cli.cli:main",
        ],
    },
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Environment :: Console",
        "Topic :: Communications :: Email",
        "Topic :: Office/Business :: Scheduling",
        "Topic :: Utilities",
    ],
)
