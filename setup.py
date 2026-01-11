from setuptools import setup, find_packages

setup(
    name="food-agent",
    version="0.1.0",
    description="Food logging MCP agent",
    packages=find_packages(),
    install_requires=[
        "mcp[cli]",
        "PyYAML",
    ],
    package_data={
        "food_agent": ["app.yaml"],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "food-agent=food_agent.cli.main:cli",
        ],
    },
    python_requires=">=3.10",
)
