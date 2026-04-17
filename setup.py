from setuptools import setup, find_packages

# 仅安装tools自定义包的配置
setup(
    name="roboos-all",  # 自定义包名（可随意改，如tools-core，仅用于pip识别）
    version="0.1.0",      # 版本号，可自行修改
    # 仅指定安装tools包（精准匹配，不包含其他包）
    packages=["tools", "slaver"],
    python_requires=">=3.8",  # 适配你的Python3.10环境
)
