from setuptools import setup, find_packages
import sys
from core.version import APP_VERSION

_darwin = sys.platform == "darwin"

setup(
    name="elyan",
    version=APP_VERSION,
    description="Elyan — Özerk AI Operatör / Dijital Çalışan",
    author="Elyan Team",
    python_requires=">=3.11",
    package_dir={"": "."},
    packages=find_packages(exclude=["tests*", "*.tests"]),
    install_requires=[
        # Core
        "pydantic>=2.0.0",
        "json5>=0.9.0",
        "psutil>=5.9.0",
        "requests>=2.28.0",
        "httpx>=0.28.0",
        "aiohttp>=3.9.0",
        "python-dotenv>=1.0.0",
        "qasync>=0.27.0",
        # CLI
        "click>=8.1.0",
        "croniter>=2.0.0",
        # Messaging
        "python-telegram-bot>=22.0",
        # AI providers
        "groq>=0.11.0",
        "google-generativeai>=0.8.0",
        # Data / scraping
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
        "Pillow>=10.0.0",
        "numpy>=1.26.0",
        "scikit-learn>=1.4.0",
        "sentence-transformers>=3.0.0",
        # Office
        "python-docx>=1.1.0",
        "openpyxl>=3.1.0",
        "pdfplumber>=0.10.0",
        "pypdf>=3.0.0",
        "python-pptx>=1.0.0",
        "reportlab>=4.0.0",
        # Scheduling
        "apscheduler>=3.10.0",
        "feedparser>=6.0.0",
        "watchdog>=3.0.0",
        # Security
        "cryptography>=42.0.0",
        "keyring>=25.0.0",
    ],
    extras_require={
        "ui": [
            "PyQt6>=6.6.0",
            "matplotlib>=3.7.0",
        ] + (["pyobjc-framework-Cocoa>=10.1", "rumps>=0.4.0"] if _darwin else []),
        "voice": [
            "openai-whisper>=20240927",
            "pyttsx3>=2.90",
            "pydub>=0.25.0",
        ],
        "browser": [
            "playwright>=1.40.0",
        ],
        "research": [
            "numpy>=1.26.0",
            "scikit-learn>=1.4.0",
            "sentence-transformers>=3.0.0",
        ],
        "dev": [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.23.0",
            "pytest-cov>=4.0.0",
            "ruff>=0.3.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "elyan=elyan_entrypoint:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "License :: OSI Approved :: MIT License",
    ],
)
