from setuptools import setup, find_packages

setup(
    name="ai_test_framework",
    version="1.0.0",
    description="AI Test Script Automation Framework",
    packages=find_packages(),
    python_requires=">=3.7",
    install_requires=[
        "pyserial>=3.5",
        "icmplib>=3.0.3",
        "pysnmp>=4.4.12",
        "pyasn1>=0.4.8",
        "pycryptodomex>=3.18.0",
    ],
    extras_require={
        "packet_analysis": [
            "scapy>=2.5.0",
        ],
    },
)
